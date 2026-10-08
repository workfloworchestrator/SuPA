"""Unit tests for the Ciena 8190 NRM backend.

The NETCONF session is a mock whose ``get`` returns canned device configuration, so no device is needed.
"""

from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
import structlog

from supa.job.shared import NsiException
from supa.nrm.backend import STP
from supa.nrm.backends.ciena8190 import Backend, BackendSettings, Ciena8190

CANDIDATE_CAPABILITY = "urn:ietf:params:netconf:capability:candidate:1.0"

# One circuit between port 22 and 23 on VLAN 2394, plus a forwarding domain with a single flow point.
CLASSIFIERS_XML = """
<data>
  <classifiers xmlns="urn:ciena:params:xml:ns:yang:ciena-pn::ciena-mef-classifier">
    <classifier><name>CL-22-2394</name><filter-entry><vtags><vlan-id>2394</vlan-id></vtags></filter-entry></classifier>
    <classifier><name>CL-23-2394</name><filter-entry><vtags><vlan-id>2394</vlan-id></vtags></filter-entry></classifier>
    <classifier><name>CL-no-vlan</name></classifier>
  </classifiers>
</data>
"""
FLOW_POINTS_XML = """
<data>
  <fps xmlns="urn:ciena:params:xml:ns:yang:ciena-pn:ciena-mef-fp">
    <fp><name>FP-22-2394</name><fd-name>FD-22-23</fd-name><logical-port>22</logical-port>
      <classifier-list>CL-22-2394</classifier-list></fp>
    <fp><name>FP-23-2394</name><admin-state>disabled</admin-state><fd-name>FD-22-23</fd-name>
      <logical-port>23</logical-port><classifier-list>CL-23-2394</classifier-list></fp>
    <fp><name>FP-24-2394</name><fd-name>FD-single</fd-name><logical-port>24</logical-port>
      <classifier-list>CL-22-2394</classifier-list></fp>
  </fps>
</data>
"""
FORWARDING_DOMAINS_XML = """
<data>
  <fds xmlns="urn:ciena:params:xml:ns:yang:ciena-pn:ciena-mef-fd">
    <fd><name>FD-22-23</name></fd>
    <fd><name>FD-single</name></fd>
  </fds>
</data>
"""
DEVICE = {
    Ciena8190.GET_CLASSIFIERS: CLASSIFIERS_XML,
    Ciena8190.GET_FLOW_POINTS: FLOW_POINTS_XML,
    Ciena8190.GET_FORWARDING_DOMAINS: FORWARDING_DOMAINS_XML,
}
CIRCUIT = {"src_port_id": "22", "src_vlan": 2394, "dst_port_id": "23", "dst_vlan": 2394}


class TopologyBackend(Backend):
    """Backend with a fixed topology instead of the one from the database."""

    def topology(self) -> List[STP]:
        """Return two STPs, one with a VLAN range and one with a list of VLANs."""
        return [
            STP(stp_id="ams", port_id="22", vlans="2300-2400"),
            STP(stp_id="nyc", port_id="23", vlans="2394,3000-3100"),
        ]


def make_manager(device: Dict[str, str], candidate: bool) -> MagicMock:
    """Build a mock NETCONF manager that answers ``get`` from ``device``."""
    manager = MagicMock(name="Manager")
    manager.get.side_effect = lambda subtree: SimpleNamespace(data_xml=device[subtree[1]])
    manager.server_capabilities = [CANDIDATE_CAPABILITY] if candidate else []
    return manager


def make_backend(device: Dict[str, str] = DEVICE, candidate: bool = True) -> Backend:
    """Build a ``Backend`` without ``ciena8190.env`` discovery or a device connection."""
    backend = object.__new__(TopologyBackend)
    backend.log = structlog.get_logger()
    backend._settings = BackendSettings(host="device.test", port=830, username="supa", password="secret")  # noqa: S106
    backend._manager = make_manager(device, candidate)
    backend._capabilities = []
    backend._is_candidate_flag = None
    return backend


def connection_args(circuit_id: str | None = "circuit", **overrides: Any) -> Dict[str, Any]:
    """Return the backend method arguments for ``CIRCUIT``."""
    return {"connection_id": uuid4(), "bandwidth": 1000, **CIRCUIT, "circuit_id": circuit_id, **overrides}


def edited_configs(backend: Backend) -> List[str]:
    """Return the config of every ``edit_config`` call, in order."""
    return [call.kwargs["config"] for call in backend._manager.edit_config.call_args_list]


def test_init_reads_env_file(tmp_path: Path) -> None:
    """``__init__`` reads the device settings from ``ciena8190.env``."""
    env_file = tmp_path / "ciena8190.env"
    env_file.write_text("host=device.test\nport=830\n")
    with patch("supa.nrm.backends.ciena8190.find_file", return_value=env_file):
        backend = Backend()
    assert (backend._settings.host, backend._settings.port) == ("device.test", 830)
    assert backend._manager is None


@pytest.mark.parametrize(
    ("element", "expected"),
    [
        pytest.param([1, 2], [1, 2], id="list"),
        pytest.param({"name": "fp"}, [{"name": "fp"}], id="single-element"),
    ],
)
def test_iter(element: Any, expected: List[Any]) -> None:
    """``_iter`` yields the elements of a list, or the single element itself."""
    assert list(make_backend()._iter(element)) == expected


@pytest.mark.parametrize(
    ("port_id", "vlan", "expected"),
    [
        pytest.param("22", 2394, "ams", id="vlan-range"),
        pytest.param("23", 2394, "nyc", id="single-vlan"),
        pytest.param("23", 3050, "nyc", id="second-range"),
    ],
)
def test_get_stp_id(port_id: str, vlan: int, expected: str) -> None:
    """``_get_stp_id`` finds the STP whose VLANs on the port include the VLAN."""
    assert make_backend()._get_stp_id(port_id, vlan) == expected


@pytest.mark.parametrize(
    ("port_id", "vlan", "message"),
    [
        pytest.param("99", 2394, "Port 99 not found", id="unknown-port"),
        pytest.param("23", 2395, "VLAN 2395 not found on the port 23", id="unknown-vlan"),
    ],
)
def test_get_stp_id_not_found(port_id: str, vlan: int, message: str) -> None:
    """``_get_stp_id`` raises when the port or VLAN is not in the topology."""
    with pytest.raises(NsiException, match=message):
        make_backend()._get_stp_id(port_id, vlan)


def test_get_manager_connects_once() -> None:
    """``_get_manager`` connects with the configured settings and reuses the session."""
    backend = make_backend()
    backend._manager = None
    with patch("supa.nrm.backends.ciena8190.manager.connect") as connect:
        assert backend._get_manager() is backend._get_manager() is connect.return_value
    connect.assert_called_once()
    assert connect.call_args.kwargs["host"] == "device.test"


def test_get_manager_connect_failure() -> None:
    """``_get_manager`` raises an ``NsiException`` when the device cannot be reached."""
    backend = make_backend()
    backend._manager = None
    with patch("supa.nrm.backends.ciena8190.manager.connect", side_effect=OSError("unreachable")):
        with pytest.raises(NsiException, match="unreachable"):
            backend._get_manager()


@pytest.mark.parametrize(
    ("candidate", "target"),
    [
        pytest.param(True, Ciena8190.CANDIDATE, id="candidate"),
        pytest.param(False, Ciena8190.RUNNING, id="running"),
    ],
)
def test_get_target(candidate: bool, target: str) -> None:
    """``_get_target`` uses the candidate datastore when the device supports it."""
    assert make_backend(candidate=candidate)._get_target() == target


def test_parse_classifiers() -> None:
    """``_parse_classifiers`` returns each classifier with its VLAN and skips one without."""
    assert make_backend()._parse_classifiers() == {
        "CL-22-2394": {"name": "CL-22-2394", "vlan": 2394},
        "CL-23-2394": {"name": "CL-23-2394", "vlan": 2394},
    }


def test_parse_flow_points() -> None:
    """``_parse_flow_points`` returns each flow point with its admin state, port, FD and classifiers."""
    fps = make_backend()._parse_flow_points()
    assert fps["FP-22-2394"] == {
        "name": "FP-22-2394",
        "admin_state": True,
        "port": "22",
        "fd": "FD-22-23",
        "classifiers": ["CL-22-2394"],
    }
    assert fps["FP-23-2394"]["admin_state"] is False
    assert len(fps) == 3


def test_parse_forwarding_domains() -> None:
    """``_parse_forwarding_domains`` returns each forwarding domain by name."""
    assert make_backend()._parse_forwarding_domains() == {
        "FD-22-23": {"name": "FD-22-23"},
        "FD-single": {"name": "FD-single"},
    }


@pytest.mark.parametrize("method", ["_parse_classifiers", "_parse_flow_points", "_parse_forwarding_domains"])
def test_parse_failure(method: str) -> None:
    """A failed ``get`` is raised as an ``NsiException``."""
    backend = make_backend()
    backend._manager.get.side_effect = OSError("session closed")
    with pytest.raises(NsiException, match="Failed to parse"):
        getattr(backend, method)()


def test_get_lookup() -> None:
    """``_get_lookup`` maps both directions of a circuit and ignores a forwarding domain with one flow point."""
    lookup = make_backend()._get_lookup()
    circuit = {
        "fd": "FD-22-23",
        "flow_points": {"FP-22-2394", "FP-23-2394"},
        "classifiers": {"CL-22-2394", "CL-23-2394"},
    }
    assert lookup == {("22", 2394, "23", 2394): circuit, ("23", 2394, "22", 2394): circuit}


def test_get_lookup_multiple_classifiers() -> None:
    """``_get_lookup`` raises on a flow point with more than one classifier."""
    device = {
        **DEVICE,
        Ciena8190.GET_FLOW_POINTS: FLOW_POINTS_XML.replace(
            "<classifier-list>CL-22-2394</classifier-list></fp>",
            "<classifier-list>CL-22-2394</classifier-list><classifier-list>CL-23-2394</classifier-list></fp>",
            1,
        ),
    }
    with pytest.raises(NsiException, match="Multiple classifiers configured on the single flow point: FP-22-2394"):
        make_backend(device)._get_lookup()


@pytest.mark.parametrize(
    ("candidate", "committed"),
    [
        pytest.param(True, True, id="candidate"),
        pytest.param(False, False, id="running"),
    ],
)
def test_activate(candidate: bool, committed: bool) -> None:
    """``activate`` creates classifiers, forwarding domain and flow points, then validates and commits."""
    backend = make_backend(candidate=candidate)
    circuit_id = backend.activate(**connection_args(circuit_id=None))
    assert circuit_id
    assert edited_configs(backend) == [
        Ciena8190.create_classifier(name="opennsa-ams-2394", vlan=2394),
        Ciena8190.create_classifier(name="opennsa-nyc-2394", vlan=2394),
        Ciena8190.create_forwarding_domain(name="opennsa-ams-nyc-2394-2394", description="opennsa-ams-nyc-2394-2394"),
        Ciena8190.create_flow_point(
            name="opennsa-ams-2394",
            fd="opennsa-ams-nyc-2394-2394",
            port="22",
            classifier="opennsa-ams-2394",
            description="opennsa-ams-2394",
        ),
        Ciena8190.create_flow_point(
            name="opennsa-nyc-2394",
            fd="opennsa-ams-nyc-2394-2394",
            port="23",
            classifier="opennsa-nyc-2394",
            description="opennsa-nyc-2394",
        ),
    ]
    backend._manager.validate.assert_called_once_with(source=Ciena8190.CANDIDATE if candidate else Ciena8190.RUNNING)
    assert backend._manager.commit.called is committed


def test_activate_vlans_must_match() -> None:
    """``activate`` refuses VLAN translation."""
    backend = make_backend()
    with pytest.raises(NsiException, match="VLANs must match"):
        backend.activate(**connection_args(dst_vlan=2395))
    backend._manager.edit_config.assert_not_called()


def test_deactivate() -> None:
    """``deactivate`` disables both flow points of the circuit and commits."""
    backend = make_backend()
    backend.deactivate(**connection_args())
    assert sorted(edited_configs(backend)) == sorted(
        [Ciena8190.disable_flow_point(name="FP-22-2394"), Ciena8190.disable_flow_point(name="FP-23-2394")]
    )
    backend._manager.commit.assert_called_once()


def test_terminate() -> None:
    """``terminate`` deletes flow points, then the forwarding domain, then the classifiers, and commits."""
    backend = make_backend()
    backend.terminate(**connection_args())
    configs = edited_configs(backend)
    assert set(configs[:2]) == {
        Ciena8190.delete_flow_point(name="FP-22-2394"),
        Ciena8190.delete_flow_point(name="FP-23-2394"),
    }
    assert configs[2] == Ciena8190.delete_forwarding_domain(name="FD-22-23")
    assert set(configs[3:]) == {
        Ciena8190.delete_classifier(name="CL-22-2394"),
        Ciena8190.delete_classifier(name="CL-23-2394"),
    }
    backend._manager.commit.assert_called_once()


@pytest.mark.parametrize("method", ["deactivate", "terminate"])
def test_circuit_not_on_device(method: str) -> None:
    """``deactivate`` and ``terminate`` raise when the circuit is not on the device."""
    backend = make_backend()
    with pytest.raises(NsiException, match="No such circuit exists"):
        getattr(backend, method)(**connection_args(src_vlan=2000, dst_vlan=2000))
    backend._manager.edit_config.assert_not_called()


@pytest.mark.parametrize("circuit_id", [None, ""], ids=["none", "empty"])
def test_terminate_never_activated(circuit_id: str | None) -> None:
    """``terminate`` does not contact the device for a connection without a circuit_id."""
    backend = make_backend()
    backend.terminate(**connection_args(circuit_id=circuit_id))
    backend._manager.get.assert_not_called()
    backend._manager.edit_config.assert_not_called()


@pytest.mark.parametrize("method", ["deactivate", "terminate"])
def test_circuit_created_after_first_lookup(method: str) -> None:
    """``deactivate`` and ``terminate`` re-read the device, so they find a circuit created after the first read."""
    no_fds = '<data><fds xmlns="urn:ciena:params:xml:ns:yang:ciena-pn:ciena-mef-fd"/></data>'
    device = {**DEVICE, Ciena8190.GET_FORWARDING_DOMAINS: no_fds}
    backend = make_backend(device)
    assert backend._get_lookup() == {}
    device[Ciena8190.GET_FORWARDING_DOMAINS] = FORWARDING_DOMAINS_XML
    getattr(backend, method)(**connection_args())
    backend._manager.commit.assert_called_once()


@pytest.mark.parametrize(
    ("method", "kwargs"),
    [
        pytest.param("_create_classifier", {"name": "c", "vlan": 2394}, id="create-classifier"),
        pytest.param("_create_forwarding_domain", {"name": "fd"}, id="create-forwarding-domain"),
        pytest.param(
            "_create_flow_point", {"name": "fp", "fd": "fd", "port": "22", "classifier": "c"}, id="create-flow-point"
        ),
        pytest.param("_delete_classifier", {"name": "c"}, id="delete-classifier"),
        pytest.param("_delete_forwarding_domain", {"name": "fd"}, id="delete-forwarding-domain"),
        pytest.param("_delete_flow_point", {"name": "fp"}, id="delete-flow-point"),
        pytest.param("_disable_flow_point", {"name": "fp"}, id="disable-flow-point"),
    ],
)
@pytest.mark.parametrize("candidate", [True, False], ids=["candidate", "running"])
def test_edit_config_failure(method: str, kwargs: Dict[str, Any], candidate: bool) -> None:
    """A failed ``edit_config`` discards the candidate configuration and raises an ``NsiException``."""
    backend = make_backend(candidate=candidate)
    backend._manager.edit_config.side_effect = OSError("rejected")
    with pytest.raises(NsiException, match="Failed to"):
        getattr(backend, method)(**kwargs)
    assert backend._manager.discard_changes.called is candidate


@pytest.mark.parametrize(
    ("method", "operation"),
    [
        pytest.param("_validate", "validate", id="validate"),
        pytest.param("_commit", "commit", id="commit"),
    ],
)
def test_validate_or_commit_failure(method: str, operation: str) -> None:
    """A failed validate or commit discards the candidate configuration and raises an ``NsiException``."""
    backend = make_backend()
    getattr(backend._manager, operation).side_effect = OSError("invalid")
    with pytest.raises(NsiException, match=f"Failed to {operation} the configuration"):
        getattr(backend, method)()
    backend._manager.discard_changes.assert_called_once()


def test_discard_failure() -> None:
    """A failed discard raises an ``NsiException``."""
    backend = make_backend()
    backend._manager.discard_changes.side_effect = OSError("locked")
    with pytest.raises(NsiException, match="Failed to discard the configuration"):
        backend._discard()
