from typing import Any
from uuid import UUID

from supa.connection.fsm import (
    DataPlaneStateMachine,
    LifecycleStateMachine,
    ProvisionStateMachine,
    ReservationStateMachine,
)
from supa.db.model import Request, Reservation, Topology
from supa.grpc_nsi.connection_common_pb2 import RESERVE_CHECKING, GenericAcknowledgment
from supa.grpc_nsi.connection_requester_pb2 import (
    DataPlaneStateChangeRequest,
    ErrorRequest,
    GenericConfirmedRequest,
    GenericFailedRequest,
    ReserveConfirmedRequest,
    ReserveTimeoutRequest,
)
from supa.grpc_nsi.connection_requester_pb2_grpc import ConnectionRequesterServicer
from supa.util.timestamp import NO_END_DATE


class Servicer(ConnectionRequesterServicer):
    """Fake servicer to mock replies."""

    def ReserveConfirmed(self, request: ReserveConfirmedRequest, context: Any) -> GenericAcknowledgment:
        """Fake ReserveConfirmed to return mocked GenericAcknowledgment."""
        from supa.db.session import db_session

        assert request.connection_id

        with db_session() as session:
            reservation = (
                session.query(Reservation).filter(Reservation.connection_id == UUID(request.connection_id)).one()
            )
            assert reservation.reservation_state == ReservationStateMachine.ReserveHeld.value

        return GenericAcknowledgment(header=request.header)

    def ReserveFailed(self, request: GenericFailedRequest, context: Any) -> GenericAcknowledgment:
        """Fake ReserveFailed to return mocked GenericAcknowledgment."""
        from supa.db.session import db_session

        assert request.connection_id
        assert request.HasField("service_exception")
        assert request.HasField("connection_states")
        assert request.connection_states.reservation_state == RESERVE_CHECKING

        test_hit_count = 0
        with db_session() as session:
            reservation = (
                session.query(Reservation).filter(Reservation.connection_id == UUID(request.connection_id)).one()
            )
            port = session.query(Topology).filter(Topology.stp_id == reservation.dst_stp_id).one_or_none()
            # By this time the reservation in the database already transitioned to ReserveFailed.
            assert reservation.reservation_state == ReservationStateMachine.ReserveFailed.value
            # test_reserve_job_reserve_failed_src_stp_id_equals_dst_stp_id()
            if reservation.src_stp_id == reservation.dst_stp_id:
                test_hit_count += 1
                assert request.service_exception.error_id == "00407"
                assert len(request.service_exception.variables) == 3
                assert request.service_exception.variables[0].type == "providerNSA"
                assert request.service_exception.variables[1].type == "sourceSTP"
                assert request.service_exception.variables[2].type == "destSTP"
                assert request.service_exception.variables[1].value == request.service_exception.variables[2].value
            # test_reserve_job_reserve_failed_unknown_stp_id()
            if reservation.dst_stp_id == "unknown_stp":
                test_hit_count += 1
                assert request.service_exception.error_id == "00701"
                assert len(request.service_exception.variables) == 1
                assert request.service_exception.variables[0].type == "destSTP"
                assert "unknown_stp" in request.service_exception.variables[0].value
            # test_reserve_job_reserve_failed_disabled_stp_id()
            if port and not port.enabled:
                test_hit_count += 1
                assert request.service_exception.error_id == "00701"
                assert len(request.service_exception.variables) == 1
                assert request.service_exception.variables[0].type == "destSTP"
            # test_reserve_job_reserve_failed_unknown_domain_stp_id()
            if reservation.dst_domain == "unknown_domain":
                test_hit_count += 1
                assert request.service_exception.error_id == "00701"
                assert len(request.service_exception.variables) == 1
                assert request.service_exception.variables[0].type == "destSTP"
                assert "unknown_domain" in request.service_exception.variables[0].value
            # test_reserve_job_reserve_failed_unknown_topology_stp_id()
            if reservation.dst_topology == "unknown_topology":
                test_hit_count += 1
                assert request.service_exception.error_id == "00701"
                assert len(request.service_exception.variables) == 1
                assert request.service_exception.variables[0].type == "destSTP"
                assert "unknown_topology" in request.service_exception.variables[0].value
            # test_reserve_job_reserve_failed_empty_vlans_stp_id()
            if reservation.dst_vlans == "":
                test_hit_count += 1
                assert request.service_exception.error_id == "00709"
                assert len(request.service_exception.variables) == 1
                assert request.service_exception.variables[0].type == "destSTP"
                assert request.service_exception.variables[0].value.endswith("vlan=")
            # test_reserve_job_reserve_failed_to_much_bandwidth()
            if reservation.bandwidth == 1000000000:
                test_hit_count += 1
                assert request.service_exception.error_id == "00705"
                assert len(request.service_exception.variables) == 2
                assert request.service_exception.variables[0].type == "capacity"
                assert request.service_exception.variables[0].value == "1000000000"
                assert request.service_exception.variables[1].type == "sourceSTP"
                assert "requested: 1 Pbit/s, available: 1 Gbit/s" in request.service_exception.text
            # test_reserve_job_reserve_failed_no_matching_vlan()
            if reservation.dst_vlans == "3333":
                test_hit_count += 1
                assert request.service_exception.error_id == "00704"
                assert len(request.service_exception.variables) == 1
                assert request.service_exception.variables[0].type == "destSTP"
                assert "vlan=3333" in request.service_exception.variables[0].value
                assert "requested: 3333, available: 1779-1799" in request.service_exception.text
            # test_reserve_job_reserve_failed_all_vlans_in_use()
            if port and port.vlans == "":
                test_hit_count += 1
                assert request.service_exception.error_id == "00704"
                assert len(request.service_exception.variables) == 1
                assert request.service_exception.variables[0].type == "destSTP"
                assert "all VLANs in use" in request.service_exception.text
        assert test_hit_count == 1

        return GenericAcknowledgment(header=request.header)

    def ReserveCommitConfirmed(self, request: GenericConfirmedRequest, context: Any) -> GenericAcknowledgment:
        """Fake ReserveCommitConfirmed to return mocked GenericAcknowledgment."""
        from supa.db.session import db_session

        assert request.connection_id

        with db_session() as session:
            reservation = (
                # By this time the reservation in the database already transitioned to ReserveFailed.
                session.query(Reservation)
                .filter(Reservation.connection_id == UUID(request.connection_id))
                .one()
            )
            assert reservation.reservation_state == ReservationStateMachine.ReserveStart.value

        return GenericAcknowledgment(header=request.header)

    def ReserveAbortConfirmed(self, request: GenericConfirmedRequest, context: Any) -> GenericAcknowledgment:
        """Fake ReserveAbortConfirmed to return mocked GenericAcknowledgment."""
        return GenericConfirmedRequest(header=request.header)

    def ReserveTimeout(self, request: ReserveTimeoutRequest, context: Any) -> GenericAcknowledgment:
        """Fake ReserveTimeout to return mocked GenericAcknowledgment."""
        return GenericAcknowledgment(header=request.header)

    def ProvisionConfirmed(self, request: GenericConfirmedRequest, context: Any) -> GenericAcknowledgment:
        """Fake ProvisionConfirmed to return mocked GenericAcknowledgment."""
        from supa.db.session import db_session

        assert request.connection_id

        with db_session() as session:
            reservation = (
                session.query(Reservation).filter(Reservation.connection_id == UUID(request.connection_id)).one()
            )
            # test_provision_job_provision_confirmed()
            assert reservation.provision_state == ProvisionStateMachine.Provisioned.value

        return GenericAcknowledgment(header=request.header)

    def ReleaseConfirmed(self, request: GenericConfirmedRequest, context: Any) -> GenericAcknowledgment:
        """Fake ReleaseConfirmed to return mocked GenericAcknowledgment."""
        from supa.db.session import db_session

        assert request.connection_id

        with db_session() as session:
            reservation = (
                session.query(Reservation).filter(Reservation.connection_id == UUID(request.connection_id)).one()
            )
            assert reservation.provision_state == ProvisionStateMachine.Released.value

        return GenericAcknowledgment(header=request.header)

    def Error(self, request: ErrorRequest, context: Any) -> GenericAcknowledgment:
        """Fake Error to return mocked GenericAcknowledgment.

        The correlationId carried in the NSI CS header structure
        will identify the original request associated with this error message.
        """
        from supa.db.session import db_session

        assert request.HasField("service_exception")

        test_hit_count = 0
        with db_session() as session:
            reservation = (
                session.query(Reservation)
                .join(Request, Request.connection_id == Reservation.connection_id)
                .filter(Request.correlation_id == UUID(request.header.correlation_id))
                .one()
            )
            # test_provision_job_already_terminated()
            if (
                reservation.provision_state == ProvisionStateMachine.Provisioning.value
                and reservation.lifecycle_state == LifecycleStateMachine.Terminated.value
            ):
                test_hit_count += 1
                assert request.service_exception.error_id == "00200"
                assert len(request.service_exception.variables) == 1
                assert request.service_exception.variables[0].type == "connectionId"
                assert "Reservation already terminated" in request.service_exception.text
            # test_provision_cannot_auto_start()
            if (
                reservation.provision_state == ProvisionStateMachine.Provisioning.value
                and reservation.data_plane_state == DataPlaneStateMachine.Activated.value
            ):
                test_hit_count += 1
                assert request.service_exception.error_id == "00201"
                assert len(request.service_exception.variables) == 1
                assert request.service_exception.variables[0].type == "connectionId"
                assert (
                    "Connection state machine is in invalid state for received message"
                    in request.service_exception.text
                )
            # test_provision_cannot_activate()
            if (
                reservation.provision_state == ProvisionStateMachine.Provisioning.value
                and reservation.data_plane_state == DataPlaneStateMachine.ActivateFailed.value
            ):
                test_hit_count += 1
                assert request.service_exception.error_id == "00201"
                assert len(request.service_exception.variables) == 1
                assert request.service_exception.variables[0].type == "connectionId"
                assert "Can't activate_request when in ActivateFailed" in request.service_exception.text
            # test_release_job_already_terminated()
            if (
                reservation.provision_state == ProvisionStateMachine.Releasing.value
                and reservation.lifecycle_state == LifecycleStateMachine.Terminated.value
            ):
                test_hit_count += 1
                assert request.service_exception.error_id == "00200"
                assert len(request.service_exception.variables) == 1
                assert request.service_exception.variables[0].type == "connectionId"
                assert "Reservation already terminated" in request.service_exception.text
        assert test_hit_count == 1

        return GenericAcknowledgment(header=request.header)

    def TerminateConfirmed(self, request: GenericConfirmedRequest, context: Any) -> GenericAcknowledgment:
        """Fake TerminateConfirmed to return mocked GenericAcknowledgment."""
        from supa.db.session import db_session

        assert request.connection_id

        with db_session() as session:
            reservation = (
                session.query(Reservation).filter(Reservation.connection_id == UUID(request.connection_id)).one()
            )
            # test_provision_job_provision_confirmed()
            assert reservation.lifecycle_state == LifecycleStateMachine.Terminated.value

        return GenericAcknowledgment(header=request.header)

    def DataPlaneStateChange(self, request: DataPlaneStateChangeRequest, context: Any) -> GenericAcknowledgment:
        """Fake DataPlaneStateChange to return mocked GenericAcknowledgment."""
        from supa.db.session import db_session

        assert request.HasField("notification")
        assert request.HasField("data_plane_status")

        test_hit_count = 0
        with db_session() as session:
            reservation = (
                session.query(Reservation)
                .join(Request, Request.connection_id == Reservation.connection_id)
                .filter(Request.correlation_id == UUID(request.header.correlation_id))
                .one()
            )

            # test_activate_job_end_date()
            if (
                reservation.data_plane_state == DataPlaneStateMachine.AutoEnd.value
                and reservation.end_time != NO_END_DATE
            ):
                test_hit_count += 1
                assert request.data_plane_status.active
                assert request.data_plane_status.version_consistent
            # test_activate_job_no_end_date()
            if (
                reservation.data_plane_state == DataPlaneStateMachine.Activated.value
                and reservation.end_time == NO_END_DATE
            ):
                test_hit_count += 1
                assert request.data_plane_status.active
                assert request.data_plane_status.version_consistent
            # test_deactivate_job()
            if reservation.data_plane_state == DataPlaneStateMachine.Deactivated.value:
                test_hit_count += 1
                assert not request.data_plane_status.active
                assert request.data_plane_status.version_consistent

        assert test_hit_count == 1

        return GenericAcknowledgment(header=request.header)
