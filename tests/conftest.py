import time
from concurrent import futures
from datetime import datetime, timedelta, timezone
from typing import Generator
from uuid import UUID, uuid4

import grpc
import pytest
from apscheduler.jobstores.base import JobLookupError
from sqlalchemy import Column
from sqlalchemy.orm import aliased

from supa import init_app, settings
from supa.connection.fsm import (
    DataPlaneStateMachine,
    LifecycleStateMachine,
    ProvisionStateMachine,
    ReservationStateMachine,
)
from supa.db.model import Connection, P2PCriteria, Request, Reservation, Schedule, Topology
from supa.grpc_nsi import connection_provider_pb2_grpc
from supa.job.dataplane import AutoEndJob, AutoStartJob
from supa.job.reserve import ReserveTimeoutJob
from supa.util.timestamp import NO_END_DATE
from supa.util.type import RequestType


@pytest.fixture(autouse=True, scope="session")
def init(tmp_path_factory: pytest.TempPathFactory) -> Generator:
    """Initialize application and start the connection provider gRPC server."""
    settings.database_file = tmp_path_factory.mktemp("supa") / "supa.db"
    init_app()
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=settings.grpc_server_max_workers))

    # Safe to import, now that `init_app()` has been called
    from supa.connection.provider.server import ConnectionProviderService

    connection_provider_pb2_grpc.add_ConnectionProviderServicer_to_server(ConnectionProviderService(), server)
    server.add_insecure_port(f"{settings.grpc_server_insecure_host}:{settings.grpc_server_insecure_port}")

    server.start()

    yield

    # better to check if all jobs are finished, for now we just sleep on it
    time.sleep(1)


@pytest.fixture(autouse=True, scope="session")
def add_stp_ids(init: Generator) -> None:
    """Add standard STPs to database."""
    from supa.db.session import db_session

    with db_session() as session:
        session.add(
            Topology(
                stp_id="port1",
                port_id="2d35f97c-7e90-4f2d-bc52-d22d05d972f4",
                vlans="1779-1799",
                bandwidth=1000,
                enabled=True,
            )
        )
        session.add(
            Topology(
                stp_id="port2",
                port_id="port.id",
                vlans="1779-1799",
                bandwidth=1000,
                enabled=True,
            )
        )
        session.add(
            Topology(
                stp_id="enni.port1",
                port_id="52fa0ee0-e10a-44a1-b095-ea1bcc7a60f4",
                vlans="2-4094",
                bandwidth=10000,
                description="To external network",
                is_alias_in="urn:ogf:network:domain:1999:topology:neighbour-1-out",
                is_alias_out="urn:ogf:network:domain:1999:topology:neighbour-1-in",
                enabled=True,
            )
        )
        session.add(
            Topology(
                stp_id="enni.port2",
                port_id="my_favorite_neighbour",
                vlans="1000-1009",
                bandwidth=10000,
                is_alias_in="urn:ogf:network:domain:2024::3-out",
                is_alias_out="urn:ogf:network:domain:2024::3-in",
                enabled=True,
            )
        )


@pytest.fixture()
def connection_id() -> Generator[UUID, None, None]:
    """Create new reservation in db and return connection ID."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = Reservation(
            protocol_version="application/vnd.ogf.nsi.cs.v2.provider+soap",
            requester_nsa="urn:ogf:network:example.domain:2021:requester",
            provider_nsa="urn:ogf:network:example.domain:2021:provider",
            reply_to=None,
            session_security_attributes=None,
            global_reservation_id="global reservation id",
            description="reservation 1",
            version=0,
            lifecycle_state="CREATED",
        )
        reservation.schedules.append(
            Schedule(
                version=0,
                start_time=datetime.now(timezone.utc) + timedelta(minutes=10),
                end_time=datetime.now(timezone.utc) + timedelta(minutes=20),
            )
        )
        reservation.p2p_criteria_list.append(
            P2PCriteria(
                version=0,
                bandwidth=10,
                symmetric=True,
                src_domain="example.domain:2001",
                src_topology="topology",
                src_stp_id="port1",
                src_vlans="1783",
                src_selected_vlan=1783,
                dst_domain="example.domain:2001",
                dst_topology="topology",
                dst_stp_id="port2",
                dst_vlans="1783",
                dst_selected_vlan=1783,
            )
        )
        session.add(reservation)
        session.flush()  # let db generate connection_id
        connection_id = reservation.connection_id
        request = Request(
            connection_id=connection_id,
            correlation_id=uuid4(),
            request_type=RequestType.Reserve,  # should add specific request type
            request_data=b"should add request message here",
        )
        session.add(request)

        yield connection_id

        session.delete(session.query(Reservation).filter(Reservation.connection_id == connection_id).one())
        # connection, schedule and p2p_criteria are deleted through cascade


@pytest.fixture()
def connection_id_modified(connection_id: UUID) -> None:
    """Transform a connection ID into a modified connection ID."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        reservation.version = 1
        reservation.schedules.append(
            Schedule(
                version=1,
                start_time=datetime.now(timezone.utc) + timedelta(minutes=20),
                end_time=datetime.now(timezone.utc) + timedelta(minutes=30),
            )
        )
        reservation.p2p_criteria_list.append(
            P2PCriteria(
                version=1,
                bandwidth=20,
                symmetric=True,
                src_domain="example.domain:2001",
                src_topology="topology",
                src_stp_id="port1",
                src_vlans="1783",
                src_selected_vlan=1783,
                dst_domain="example.domain:2001",
                dst_topology="topology",
                dst_stp_id="port2",
                dst_vlans="1783",
                dst_selected_vlan=1783,
            )
        )
        request = Request(
            connection_id=connection_id,
            correlation_id=uuid4(),
            request_type=RequestType.Reserve,  # should add specific request type
            request_data=b"should add request message here",
        )
        session.add(request)


@pytest.fixture
def connection(connection_id: Column) -> None:
    """Add connection record for given connection_id."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        src_topology = aliased(Topology)
        dst_topology = aliased(Topology)
        src_port_id, dst_port_id = (
            session.query(src_topology.port_id, dst_topology.port_id)
            .filter(
                P2PCriteria.connection_id == connection_id,
                P2PCriteria.version == reservation.version,
                P2PCriteria.src_stp_id == src_topology.stp_id,
                P2PCriteria.dst_stp_id == dst_topology.stp_id,
            )
            .one()
        )
        connection = Connection(
            connection_id=connection_id,
            bandwidth=10,
            src_port_id=src_port_id,
            src_vlan=reservation.p2p_criteria.src_selected_vlan,
            dst_port_id=dst_port_id,
            dst_vlan=reservation.p2p_criteria.dst_selected_vlan,
        )
        session.add(connection)


@pytest.fixture
def connection_modified(connection_id: Column, connection: None) -> None:
    """Add connection record for given connection_id."""
    from supa.db.session import db_session

    with db_session() as session:
        connection_from_db = session.query(Connection).filter(Connection.connection_id == connection_id).one()
        connection_from_db.bandwidth = 20


@pytest.fixture()
def reserve_timeout_job(connection_id: Column) -> None:
    """Schedule a ReserveTimeoutJob for connection_id."""
    from supa import scheduler

    scheduler.add_job(job := ReserveTimeoutJob(connection_id), trigger=job.trigger(), id=job.job_id)


@pytest.fixture
def src_stp_id_equals_dst_stp_id(connection_id: Column) -> None:
    """Set dst_stp_id of reservation identified by connection_id to src_stp_id."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        reservation.p2p_criteria.dst_stp_id = reservation.p2p_criteria.src_stp_id


@pytest.fixture
def unknown_stp_id(connection_id: Column) -> None:
    """Set dst_stp_id of reservation identified by connection_id to unknown."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        reservation.p2p_criteria.dst_stp_id = "unknown_stp"


@pytest.fixture
def disabled_stp(connection_id: Column) -> Generator:
    """Temporarily disable dst_stp_id of reservation identified by connection_id."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        port = session.query(Topology).filter(Topology.stp_id == reservation.p2p_criteria.dst_stp_id).one_or_none()
        port.enabled = False

    yield None

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        port = session.query(Topology).filter(Topology.stp_id == reservation.p2p_criteria.dst_stp_id).one_or_none()
        port.enabled = True


@pytest.fixture
def unknown_domain_stp_id(connection_id: Column) -> None:
    """Set dst_domain of reservation identified by connection_id to unknown."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        reservation.p2p_criteria.dst_domain = "unknown_domain"


@pytest.fixture
def unknown_topology_stp_id(connection_id: Column) -> None:
    """Set dst_topology of reservation identified by connection_id to unknown."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        reservation.p2p_criteria.dst_topology = "unknown_topology"


@pytest.fixture
def empty_vlans_stp_id(connection_id: Column) -> None:
    """Set dst_vlans of reservation identified by connection_id to empty."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        reservation.p2p_criteria.dst_vlans = ""


@pytest.fixture
def to_much_bandwidth(connection_id: Column) -> None:
    """Set bandwidth of reservation identified by connection_id to ridiculous amount."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        reservation.p2p_criteria.bandwidth = 1000000000


@pytest.fixture
def no_matching_vlan(connection_id: Column) -> None:
    """Set dst_vlans of reservation identified by connection_id to unavailable vlan."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        reservation.p2p_criteria.dst_vlans = "3333"


@pytest.fixture
def all_vlans_in_use(connection_id: Column) -> Generator:
    """Temporarily remove all vlans on dst_stp_id of reservation identified by connection_id."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        port = session.query(Topology).filter(Topology.stp_id == reservation.p2p_criteria.dst_stp_id).one_or_none()
        original_vlans = port.vlans
        port.vlans = ""

    yield None

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        port = session.query(Topology).filter(Topology.stp_id == reservation.p2p_criteria.dst_stp_id).one_or_none()
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

    job_handle = scheduler.add_job(job := ReserveTimeoutJob(connection_id), trigger=job.trigger(), id=job.job_id)

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
def releasing(connection_id: Column) -> None:
    """Set provision state machine of reservation identified by connection_id to state Releasing."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        reservation.provision_state = ProvisionStateMachine.Releasing.value


@pytest.fixture
def provisioned(connection_id: Column) -> None:
    """Set provision state machine of reservation identified by connection_id to state Provisioned."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        reservation.provision_state = ProvisionStateMachine.Provisioned.value


@pytest.fixture
def provisioning(connection_id: Column) -> None:
    """Set provision state machine of reservation identified by connection_id to state Provisioning."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        reservation.provision_state = ProvisionStateMachine.Provisioning.value


@pytest.fixture
def terminating(connection_id: Column) -> None:
    """Set lifecycle state machine of reservation identified by connection_id to state Terminating."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        reservation.lifecycle_state = LifecycleStateMachine.Terminating.value


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
def activating(connection_id: Column) -> None:
    """Set data plane state machine of reservation identified by connection_id to state Activating."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        reservation.data_plane_state = DataPlaneStateMachine.Activating.value


@pytest.fixture
def activated(connection_id: Column) -> None:
    """Set data plane state machine of reservation identified by connection_id to state Activated."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        reservation.data_plane_state = DataPlaneStateMachine.Activated.value


@pytest.fixture
def activate_failed(connection_id: Column) -> None:
    """Set data plane state machine of reservation identified by connection_id to state ActivateFailed."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        reservation.data_plane_state = DataPlaneStateMachine.ActivateFailed.value


@pytest.fixture
def auto_start(connection_id: Column) -> None:
    """Set data plane state machine of reservation identified by connection_id to state AutoStart."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        reservation.data_plane_state = DataPlaneStateMachine.AutoStart.value


@pytest.fixture
def auto_start_job(connection_id: Column) -> Generator:
    """Run AutoStartJob for connection_id."""
    from supa import scheduler

    job_handle = scheduler.add_job(job := AutoStartJob(connection_id), trigger=job.trigger(), id=job.job_id)

    yield None

    try:
        job_handle.remove()
    except JobLookupError:
        pass  # job already removed from job store


@pytest.fixture
def auto_end(connection_id: Column) -> Generator:
    """Set data plane state machine of reservation identified by connection_id to state AutoEnd."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        reservation.data_plane_state = DataPlaneStateMachine.AutoEnd.value

    from supa import scheduler

    job_handle = scheduler.add_job(job := AutoEndJob(connection_id), trigger=job.trigger(), id=job.job_id)

    yield None

    try:
        job_handle.remove()
    except JobLookupError:
        pass  # job already removed from job store


@pytest.fixture
def auto_end_job(connection_id: Column) -> Generator:
    """Run AutoEndtJob for connection_id."""
    from supa import scheduler

    job_handle = scheduler.add_job(job := AutoEndJob(connection_id), trigger=job.trigger(), id=job.job_id)

    yield None

    try:
        job_handle.remove()
    except JobLookupError:
        pass  # job already removed from job store


@pytest.fixture
def deactivating(connection_id: Column) -> None:
    """Set data plane state machine of reservation identified by connection_id to state Deactivating."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        reservation.data_plane_state = DataPlaneStateMachine.Deactivating.value


@pytest.fixture
def deactivated(connection_id: Column) -> None:
    """Set data plane state machine of reservation identified by connection_id to state Deactivated."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        reservation.data_plane_state = DataPlaneStateMachine.Deactivated.value


@pytest.fixture
def flag_reservation_timeout(connection_id: Column) -> None:
    """Set reservation timeout flag of reservation identified by connection_id to True."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        reservation.reservation_timeout = True


@pytest.fixture
def start_now(connection_id: Column) -> None:
    """Set reservation start time to now."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        reservation.schedule.start_time = datetime.now(timezone.utc)


@pytest.fixture
def no_end_time(connection_id: Column) -> None:
    """Set reservation start time to now."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        reservation.schedule.end_time = NO_END_DATE


def p2p_criteria_from_p2_criteria(p2p_criteria: P2PCriteria) -> P2PCriteria:
    """Create deepcopy of given P2PCriteria object with version set to 1."""
    return P2PCriteria(
        version=1,
        bandwidth=p2p_criteria.bandwidth,
        symmetric=p2p_criteria.symmetric,
        src_domain=p2p_criteria.src_domain,
        src_topology=p2p_criteria.src_topology,
        src_stp_id=p2p_criteria.src_stp_id,
        src_vlans=p2p_criteria.src_vlans,
        src_selected_vlan=p2p_criteria.src_selected_vlan,
        dst_domain=p2p_criteria.dst_domain,
        dst_topology=p2p_criteria.dst_topology,
        dst_stp_id=p2p_criteria.dst_stp_id,
        dst_vlans=p2p_criteria.dst_vlans,
        dst_selected_vlan=p2p_criteria.dst_selected_vlan,
    )


@pytest.fixture
def modified_start_time(connection_id: Column) -> None:
    """Add Schedule with modified start time on connection set to Provisioned and AutoStart."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        reservation.data_plane_state = DataPlaneStateMachine.AutoStart.value
        reservation.provision_state = ProvisionStateMachine.Provisioned.value
        reservation.schedules.append(
            Schedule(
                version=1,
                start_time=reservation.schedule.start_time + timedelta(minutes=1),
                end_time=reservation.schedule.end_time,
            )
        )
        reservation.p2p_criteria_list.append(p2p_criteria_from_p2_criteria(reservation.p2p_criteria))
        reservation.version = reservation.version + 1


@pytest.fixture
def modified_no_end_time(connection_id: Column) -> None:
    """Add Schedule with no end time on connection set to Provisioned and AutoEnd."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        reservation.data_plane_state = DataPlaneStateMachine.AutoEnd.value
        reservation.provision_state = ProvisionStateMachine.Provisioned.value
        reservation.schedules.append(
            Schedule(
                version=1,
                start_time=reservation.schedule.start_time,
                end_time=NO_END_DATE,
            )
        )
        reservation.p2p_criteria_list.append(p2p_criteria_from_p2_criteria(reservation.p2p_criteria))
        reservation.version = reservation.version + 1


@pytest.fixture
def modified_end_time(connection_id: Column) -> None:
    """Add Schedule with end time of 30 minutes in the future on connection set to Provisioned and Activated."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        reservation.data_plane_state = DataPlaneStateMachine.Activated.value
        reservation.provision_state = ProvisionStateMachine.Provisioned.value
        reservation.schedules.append(
            Schedule(
                version=1,
                start_time=reservation.schedule.start_time,
                end_time=datetime.now(timezone.utc) + timedelta(minutes=30),
            )
        )
        reservation.p2p_criteria_list.append(p2p_criteria_from_p2_criteria(reservation.p2p_criteria))
        reservation.version = reservation.version + 1


@pytest.fixture
def modified_bandwidth(connection_id: Column) -> None:
    """Add P2PCriteria with modified bandwidth on connection set to Provisioned and Activated."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        reservation.data_plane_state = DataPlaneStateMachine.Activated.value
        reservation.provision_state = ProvisionStateMachine.Provisioned.value
        reservation.schedules.append(
            Schedule(
                version=1,
                start_time=reservation.schedule.start_time,
                end_time=reservation.schedule.end_time,
            )
        )
        new_p2p_criteria = p2p_criteria_from_p2_criteria(reservation.p2p_criteria)
        new_p2p_criteria.bandwidth = new_p2p_criteria.bandwidth + 10
        reservation.p2p_criteria_list.append(new_p2p_criteria)
        reservation.version = reservation.version + 1
