import time
from concurrent import futures
from datetime import datetime, timedelta, timezone
from typing import Generator
from uuid import uuid4

import grpc
import pytest
from apscheduler.jobstores.base import JobLookupError
from sqlalchemy import Column

from supa import init_app, settings
from supa.connection.fsm import LifecycleStateMachine, ProvisionStateMachine, ReservationStateMachine
from supa.db.model import Port, Reservation
from supa.grpc_nsi import connection_provider_pb2_grpc
from supa.job.reserve import ReserveTimeoutJob


@pytest.fixture(autouse=True, scope="session")
def init(tmp_path_factory: pytest.TempPathFactory) -> Generator:
    """Initialize application and start the connection provider gRPC server."""
    settings.database_file = tmp_path_factory.mktemp("supa") / "supa.db"
    init_app()
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=settings.grpc_server_max_workers))

    # Safe to import, now that `init_app()` has been called
    from supa.connection.provider.server import ConnectionProviderService

    connection_provider_pb2_grpc.add_ConnectionProviderServicer_to_server(ConnectionProviderService(), server)
    server.add_insecure_port(settings.grpc_server_insecure_address_port)

    server.start()

    yield

    # better to check if all jobs are finished, for now we just sleep on it
    time.sleep(1)


@pytest.fixture(autouse=True, scope="session")
def add_ports(init: Generator) -> None:
    """Add standard STPs to database."""
    from supa.db.session import db_session

    with db_session() as session:
        session.add(Port(port_id=uuid4(), name="port1", vlans="1779-1799", bandwidth=1000, enabled=True))
        session.add(Port(port_id=uuid4(), name="port2", vlans="1779-1799", bandwidth=1000, enabled=True))


@pytest.fixture()
def connection_id() -> Column:
    """Create new reservation in db and return connection ID."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = Reservation(
            correlation_id=uuid4(),
            protocol_version="application/vnd.ogf.nsi.cs.v2.provider+soap",
            requester_nsa="urn:ogf:network:example.domain:2021:requester",
            provider_nsa="urn:ogf:network:example.domain:2021:provider",
            reply_to=None,
            session_security_attributes=None,
            global_reservation_id="global reservation id",
            description="reservation 1",
            version=0,
            start_time=datetime.now(timezone.utc) + timedelta(minutes=10),
            end_time=datetime.now(timezone.utc) + timedelta(minutes=20),
            bandwidth=10,
            symmetric=True,
            src_domain="test.domain:2001",
            src_network_type="topology",
            src_port="port1",
            src_vlans=1783,
            dst_domain="test.domain:2001",
            dst_network_type="topology",
            dst_port="port2",
            dst_vlans=1783,
            lifecycle_state="CREATED",
        )
        session.add(reservation)
        session.flush()  # let db generate connection_id

        yield reservation.connection_id

        session.delete(reservation)


@pytest.fixture
def src_port_equals_dst_port(connection_id: Column) -> None:
    """Set dst_port of reservation identified by connection_id to src_port."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        reservation.dst_port = reservation.src_port


@pytest.fixture
def unknown_port(connection_id: Column) -> None:
    """Set dst_port of reservation identified by connection_id to unknown."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        reservation.dst_port = "unknown_stp"


@pytest.fixture
def disabled_port(connection_id: Column) -> Generator:
    """Temporarily disable dst_port of reservation identified by connection_id."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        port = session.query(Port).filter(Port.name == reservation.dst_port).one_or_none()
        port.enabled = False

    yield None

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        port = session.query(Port).filter(Port.name == reservation.dst_port).one_or_none()
        port.enabled = True


@pytest.fixture
def unknown_domain_port(connection_id: Column) -> None:
    """Set dst_domain of reservation identified by connection_id to unknown."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        reservation.dst_domain = "unknown_domain"


@pytest.fixture
def unknown_topology_port(connection_id: Column) -> None:
    """Set dst_network_type of reservation identified by connection_id to unknown."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        reservation.dst_network_type = "unknown_topology"


@pytest.fixture
def empty_vlans_port(connection_id: Column) -> None:
    """Set dst_vlans of reservation identified by connection_id to empty."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        reservation.dst_vlans = ""


@pytest.fixture
def to_much_bandwidth(connection_id: Column) -> None:
    """Set bandwidth of reservation identified by connection_id to ridiculous amount."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        reservation.bandwidth = 1000000000


@pytest.fixture
def no_matching_vlan(connection_id: Column) -> None:
    """Set dst_vlans of reservation identified by connection_id to unavailable vlan."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        reservation.dst_vlans = "3333"


@pytest.fixture
def all_vlans_in_use(connection_id: Column) -> Generator:
    """Temporarily remove all vlans on dst_port of reservation identified by connection_id."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        port = session.query(Port).filter(Port.name == reservation.dst_port).one_or_none()
        original_vlans = port.vlans
        port.vlans = ""

    yield None

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        port = session.query(Port).filter(Port.name == reservation.dst_port).one_or_none()
        port.vlans = original_vlans


@pytest.fixture
def reserve_checking(connection_id: Column) -> None:
    """Set reserve state machine of reservation identified by connection_id to state ReserveChecking."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        reservation.reservation_state = ReservationStateMachine.ReserveChecking.value


@pytest.fixture()
def reserve_held(connection_id: Column) -> Generator:
    """Set reserve state machine of reservation identified by connection_id to state ReserveHeld."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        reservation.reservation_state = ReservationStateMachine.ReserveHeld.value

    from supa import scheduler

    job_handle = scheduler.add_job(
        job := ReserveTimeoutJob(connection_id),
        trigger=job.trigger(),
        id=f"{str(connection_id)}-ReserveTimeoutJob",
    )

    yield None

    try:
        job_handle.remove()
    except JobLookupError:
        pass  # job already removed from job store


@pytest.fixture
def reserve_committing(connection_id: Column) -> None:
    """Set reserve state machine of reservation identified by connection_id to state ReserveCommitting."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        reservation.reservation_state = ReservationStateMachine.ReserveCommitting.value


@pytest.fixture
def reserve_aborting(connection_id: Column) -> None:
    """Set reserve state machine of reservation identified by connection_id to state ReserveAborting."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        reservation.reservation_state = ReservationStateMachine.ReserveAborting.value


@pytest.fixture
def released(connection_id: Column) -> None:
    """Set provision state machine of reservation identified by connection_id to state Released."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        reservation.provision_state = ProvisionStateMachine.Released.value


@pytest.fixture
def provisioned(connection_id: Column) -> None:
    """Set provision state machine of reservation identified by connection_id to state Provisioned."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        reservation.provision_state = ProvisionStateMachine.Provisioned.value


@pytest.fixture
def terminated(connection_id: Column) -> None:
    """Set lifecycle state machine of reservation identified by connection_id to state Terminated."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        reservation.lifecycle_state = LifecycleStateMachine.Terminated.value


@pytest.fixture
def passed_end_time(connection_id: Column) -> None:
    """Set lifecycle state machine of reservation identified by connection_id to state PassedEndTime."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        reservation.lifecycle_state = LifecycleStateMachine.PassedEndTime.value


@pytest.fixture
def flag_reservation_timeout(connection_id: Column) -> None:
    """Set reservation timeout flag of reservation identified by connection_id to True."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        reservation.reservation_timeout = True
