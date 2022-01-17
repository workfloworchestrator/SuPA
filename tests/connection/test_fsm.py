from supa.connection.fsm import (
    DataPlaneStateMachine,
    LifecycleStateMachine,
    ProvisionStateMachine,
    ReservationStateMachine,
)
from supa.db.model import Reservation


def test_reservation_state_machine() -> None:  # noqa: D103
    reservation = Reservation()
    rsm = ReservationStateMachine(reservation, state_field="reservation_state")
    #
    # reserve_request -> reserve_failed -> reserve_abort_request -> reserve_abort_confirmed
    #
    assert reservation.reservation_state == ReservationStateMachine.ReserveStart.value
    rsm.reserve_request()
    assert reservation.reservation_state == ReservationStateMachine.ReserveChecking.value
    rsm.reserve_failed()
    assert reservation.reservation_state == ReservationStateMachine.ReserveFailed.value
    rsm.reserve_abort_request()
    assert reservation.reservation_state == ReservationStateMachine.ReserveAborting.value
    rsm.reserve_abort_confirmed()
    assert reservation.reservation_state == ReservationStateMachine.ReserveStart.value
    #
    # reserve_request -> reserve_confirmed -> reserve_abort_request -> reserve_abort_confirmed
    #
    assert reservation.reservation_state == ReservationStateMachine.ReserveStart.value
    rsm.reserve_request()
    assert reservation.reservation_state == ReservationStateMachine.ReserveChecking.value
    rsm.reserve_confirmed()
    assert reservation.reservation_state == ReservationStateMachine.ReserveHeld.value
    rsm.reserve_abort_request()
    assert reservation.reservation_state == ReservationStateMachine.ReserveAborting.value
    rsm.reserve_abort_confirmed()
    assert reservation.reservation_state == ReservationStateMachine.ReserveStart.value
    #
    # reserve_request -> reserve_confirmed -> reserve_commit_request -> reserve_commit_confirmed
    #
    assert reservation.reservation_state == ReservationStateMachine.ReserveStart.value
    rsm.reserve_request()
    assert reservation.reservation_state == ReservationStateMachine.ReserveChecking.value
    rsm.reserve_confirmed()
    assert reservation.reservation_state == ReservationStateMachine.ReserveHeld.value
    rsm.reserve_commit_request()
    assert reservation.reservation_state == ReservationStateMachine.ReserveCommitting.value
    rsm.reserve_commit_confirmed()
    assert reservation.reservation_state == ReservationStateMachine.ReserveStart.value
    #
    # reserve_request -> reserve_confirmed -> reserve_commit_request -> reserve_commit_failed
    #
    assert reservation.reservation_state == ReservationStateMachine.ReserveStart.value
    rsm.reserve_request()
    assert reservation.reservation_state == ReservationStateMachine.ReserveChecking.value
    rsm.reserve_confirmed()
    assert reservation.reservation_state == ReservationStateMachine.ReserveHeld.value
    rsm.reserve_commit_request()
    assert reservation.reservation_state == ReservationStateMachine.ReserveCommitting.value
    rsm.reserve_commit_failed()
    assert reservation.reservation_state == ReservationStateMachine.ReserveStart.value
    #
    # reserve_request -> reserve_confirmed -> reserve_timeout_notification -> reserve_commit_request ->
    #   reserve_commit_confirmed
    #
    assert reservation.reservation_state == ReservationStateMachine.ReserveStart.value
    rsm.reserve_request()
    assert reservation.reservation_state == ReservationStateMachine.ReserveChecking.value
    rsm.reserve_confirmed()
    assert reservation.reservation_state == ReservationStateMachine.ReserveHeld.value
    rsm.reserve_timeout_notification()
    assert reservation.reservation_state == ReservationStateMachine.ReserveTimeout.value
    rsm.reserve_commit_request()
    assert reservation.reservation_state == ReservationStateMachine.ReserveCommitting.value
    rsm.reserve_commit_confirmed()
    assert reservation.reservation_state == ReservationStateMachine.ReserveStart.value
    #
    # reserve_request -> reserve_confirmed -> reserve_timeout_notification -> reserve_abort_request ->
    #   reserve_abort_confirmed
    #
    assert reservation.reservation_state == ReservationStateMachine.ReserveStart.value
    rsm.reserve_request()
    assert reservation.reservation_state == ReservationStateMachine.ReserveChecking.value
    rsm.reserve_confirmed()
    assert reservation.reservation_state == ReservationStateMachine.ReserveHeld.value
    rsm.reserve_timeout_notification()
    assert reservation.reservation_state == ReservationStateMachine.ReserveTimeout.value
    rsm.reserve_abort_request()
    assert reservation.reservation_state == ReservationStateMachine.ReserveAborting.value
    rsm.reserve_abort_confirmed()
    assert reservation.reservation_state == ReservationStateMachine.ReserveStart.value


def test_provision_state_machine() -> None:  # noqa: D103
    reservation = Reservation()
    psm = ProvisionStateMachine(reservation, state_field="provision_state")
    #
    # provision_request -> provision_confirmed -> release_request -> release_confirmed
    #
    assert reservation.provision_state == ProvisionStateMachine.Released.value
    psm.provision_request()
    assert reservation.provision_state == ProvisionStateMachine.Provisioning.value
    psm.provision_confirmed()
    assert reservation.provision_state == ProvisionStateMachine.Provisioned.value
    psm.release_request()
    assert reservation.provision_state == ProvisionStateMachine.Releasing.value
    psm.release_confirmed()
    assert reservation.provision_state == ProvisionStateMachine.Released.value


def test_lifecycle_state_machine() -> None:  # noqa: D103
    reservation = Reservation()
    lsm = LifecycleStateMachine(reservation, state_field="lifecycle_state")
    #
    # terminate_request -> terminate_confirmed
    #
    assert reservation.lifecycle_state == LifecycleStateMachine.Created.value
    lsm.terminate_request()
    assert reservation.lifecycle_state == LifecycleStateMachine.Terminating.value
    lsm.terminate_confirmed()
    assert reservation.lifecycle_state == LifecycleStateMachine.Terminated.value
    #
    # forced_end_notification -> terminate_request -> terminate_confirmed
    #
    reservation = Reservation()
    lsm = LifecycleStateMachine(reservation, state_field="lifecycle_state")
    assert reservation.lifecycle_state == LifecycleStateMachine.Created.value
    lsm.forced_end_notification()
    assert reservation.lifecycle_state == LifecycleStateMachine.Failed.value
    lsm.terminate_request()
    assert reservation.lifecycle_state == LifecycleStateMachine.Terminating.value
    lsm.terminate_confirmed()
    assert reservation.lifecycle_state == LifecycleStateMachine.Terminated.value
    #
    # endtime_event -> terminate_request -> terminate_confirmed
    #
    reservation = Reservation()
    lsm = LifecycleStateMachine(reservation, state_field="lifecycle_state")
    assert reservation.lifecycle_state == LifecycleStateMachine.Created.value
    lsm.endtime_event()
    assert reservation.lifecycle_state == LifecycleStateMachine.PassedEndTime.value
    lsm.terminate_request()
    assert reservation.lifecycle_state == LifecycleStateMachine.Terminating.value
    lsm.terminate_confirmed()
    assert reservation.lifecycle_state == LifecycleStateMachine.Terminated.value


def test_data_plane_state_machine() -> None:  # noqa: D103
    reservation = Reservation()
    dpsm = DataPlaneStateMachine(reservation, state_field="data_plane_state")
    #
    # auto_start_request -> deactivate_request
    #
    assert reservation.data_plane_state == DataPlaneStateMachine.Deactivated.value
    dpsm.auto_start_request()
    assert reservation.data_plane_state == DataPlaneStateMachine.AutoStart.value
    dpsm.deactivate_request()
    assert reservation.data_plane_state == DataPlaneStateMachine.Deactivated.value
    #
    #  auto_start_request -> activate_request -> activate_failed
    #
    dpsm = DataPlaneStateMachine(reservation, state_field="data_plane_state")
    assert reservation.data_plane_state == DataPlaneStateMachine.Deactivated.value
    dpsm.auto_start_request()
    assert reservation.data_plane_state == DataPlaneStateMachine.AutoStart.value
    dpsm.activate_request()
    assert reservation.data_plane_state == DataPlaneStateMachine.Activating.value
    dpsm.activate_failed()
    assert reservation.data_plane_state == DataPlaneStateMachine.ActivateFailed.value
    #
    # activate_request -> activate_confirmed
    #
    reservation.data_plane_state = DataPlaneStateMachine.Deactivated.value
    dpsm.activate_request()
    assert reservation.data_plane_state == DataPlaneStateMachine.Activating.value
    dpsm.activate_confirmed()
    assert reservation.data_plane_state == DataPlaneStateMachine.Activated.value
    #
    # auto_end_request -> deactivate_request -> deactivate_failed
    #
    reservation.data_plane_state = DataPlaneStateMachine.Activated.value
    dpsm.auto_end_request()
    assert reservation.data_plane_state == DataPlaneStateMachine.AutoEnd.value
    dpsm.deactivate_request()
    assert reservation.data_plane_state == DataPlaneStateMachine.Deactivating.value
    dpsm.deactivate_failed()
    assert reservation.data_plane_state == DataPlaneStateMachine.DeactivateFailed.value
    #
    # deactivate_request -> deactivate_confirm
    #
    reservation.data_plane_state = DataPlaneStateMachine.Activated.value
    dpsm.deactivate_request()
    assert reservation.data_plane_state == DataPlaneStateMachine.Deactivating.value
    dpsm.deactivate_confirm()
    assert reservation.data_plane_state == DataPlaneStateMachine.Deactivated.value
