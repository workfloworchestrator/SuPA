"""Tests for the topology update logic in :mod:`supa.documents.topology`.

These exercise :func:`supa.documents.topology.refresh_topology` (the lock, freshness and
exception handling and the database synchronisation) and the healthcheck contract in
:func:`supa.documents.healthcheck._check_topology` that depends on it.

The NRM is controlled by patching the ``topology`` method of the ``backend`` singleton in
:mod:`supa.nrm.backend`, which ``refresh_topology`` imports at call time.  A safety fixture
snapshots and restores the shared ``Topology`` table and module/settings state so these
tests cannot pollute the session-scoped database used by the rest of the suite.
"""

from typing import Generator
from unittest.mock import patch

import pytest

import supa.documents.topology as topology_module
from supa import settings
from supa.connection.error import GenericRmError
from supa.db.model import Topology
from supa.db.session import db_session
from supa.documents import refresh_topology_lock
from supa.documents.healthcheck import _check_topology
from supa.documents.topology import refresh_topology
from supa.job.shared import NsiException
from supa.nrm.backend import STP
from supa.util.timestamp import EPOCH, current_timestamp

BACKEND_TOPOLOGY = "supa.nrm.backend.backend.topology"


@pytest.fixture
def topology_state() -> Generator[None, None, None]:
    """Snapshot and restore the shared ``Topology`` table and refresh state around a test."""
    saved_last_refresh = topology_module.last_refresh
    saved_manual_topology = settings.manual_topology
    saved_topology_freshness = settings.topology_freshness
    saved_topology = settings.topology

    with db_session() as session:
        snapshot = [
            {column.name: getattr(row, column.name) for column in Topology.__table__.columns}
            for row in session.query(Topology).all()
        ]

    yield

    topology_module.last_refresh = saved_last_refresh
    settings.manual_topology = saved_manual_topology
    settings.topology_freshness = saved_topology_freshness
    settings.topology = saved_topology

    with db_session() as session:
        session.query(Topology).delete()
        session.bulk_insert_mappings(Topology, snapshot)


def force_refresh() -> None:
    """Configure settings/state so the next ``refresh_topology`` actually queries the NRM."""
    settings.manual_topology = False
    settings.topology_freshness = 0
    topology_module.last_refresh = EPOCH


def assert_lock_free() -> None:
    """Assert the refresh lock is not held (and leave it free)."""
    assert refresh_topology_lock.acquire(blocking=False)
    refresh_topology_lock.release()


@pytest.mark.parametrize(
    ("manual_topology", "topology_freshness", "fresh_now"),
    [
        pytest.param(True, 0, False, id="manual-topology"),
        pytest.param(False, 3600, True, id="still-fresh"),
    ],
)
def test_refresh_topology_skips_backend_call(
    topology_state: None, manual_topology: bool, topology_freshness: int, fresh_now: bool
) -> None:
    """``refresh_topology`` does not query the NRM when manual or still fresh."""
    settings.manual_topology = manual_topology
    settings.topology_freshness = topology_freshness
    topology_module.last_refresh = current_timestamp() if fresh_now else EPOCH

    with patch(BACKEND_TOPOLOGY) as mock_topology:
        refresh_topology()
        mock_topology.assert_not_called()

    assert_lock_free()


def test_refresh_topology_releases_lock_on_backend_exception(topology_state: None) -> None:
    """A backend failure releases the lock and re-raises, so refreshes are not wedged."""
    force_refresh()

    with patch(BACKEND_TOPOLOGY, side_effect=NsiException(GenericRmError, "boom")):
        with pytest.raises(NsiException):
            refresh_topology()

    assert_lock_free()


def test_refresh_topology_adds_new_stp(topology_state: None) -> None:
    """A new STP returned by the NRM is inserted into the topology table."""
    force_refresh()
    new_stp = STP(
        stp_id="test-new-stp",
        port_id="new-port",
        vlans="100-200",
        description="brand new",
        bandwidth=2000,
        enabled=True,
        topology=settings.topology,
    )

    with patch(BACKEND_TOPOLOGY, return_value=[new_stp]):
        refresh_topology()

    with db_session() as session:
        row = session.query(Topology).filter(Topology.stp_id == "test-new-stp").one_or_none()
        assert row is not None
        assert row.port_id == "new-port"
        assert row.vlans == "100-200"
        assert row.bandwidth == 2000


def test_refresh_topology_updates_existing_stp(topology_state: None) -> None:
    """An STP that already exists has its mutable fields updated from the NRM."""
    force_refresh()
    updated_stp = STP(
        stp_id="port1",
        port_id="updated-port",
        vlans="999-999",
        description="updated description",
        bandwidth=4000,
        enabled=True,
        topology=settings.topology,
    )

    with patch(BACKEND_TOPOLOGY, return_value=[updated_stp]):
        refresh_topology()

    with db_session() as session:
        row = session.query(Topology).filter(Topology.stp_id == "port1").one()
        assert row.port_id == "updated-port"
        assert row.vlans == "999-999"
        assert row.description == "updated description"
        assert row.bandwidth == 4000


def test_refresh_topology_skips_unknown_topology(topology_state: None) -> None:
    """An STP belonging to a different topology is not added to the database."""
    force_refresh()
    foreign_stp = STP(
        stp_id="test-foreign-stp",
        port_id="foreign-port",
        vlans="100-200",
        topology="some-other-topology",
    )

    with patch(BACKEND_TOPOLOGY, return_value=[foreign_stp]):
        refresh_topology()

    with db_session() as session:
        assert session.query(Topology).filter(Topology.stp_id == "test-foreign-stp").one_or_none() is None


def test_refresh_topology_disables_vanished_stp(topology_state: None) -> None:
    """An enabled STP that the NRM no longer reports is disabled (not deleted)."""
    force_refresh()

    # NRM reports no STPs at all, so every enabled STP must be disabled.
    with patch(BACKEND_TOPOLOGY, return_value=[]):
        refresh_topology()

    with db_session() as session:
        row = session.query(Topology).filter(Topology.stp_id == "port1").one()
        assert row.enabled is False


def test_check_topology_returns_false_on_nsi_exception(topology_state: None) -> None:
    """The healthcheck maps a topology-fetch ``NsiException`` to ``False`` (HTTP 503), not a raise.

    This is the contract the stack-trace fix relies on: the SURF backend now surfaces a token
    timeout as ``NsiException``, which flows through here to a clean 503 instead of escaping to
    CherryPy as a rendered traceback.
    """
    force_refresh()

    with patch(BACKEND_TOPOLOGY, side_effect=NsiException(GenericRmError, "boom")):
        assert _check_topology() is False

    assert_lock_free()
