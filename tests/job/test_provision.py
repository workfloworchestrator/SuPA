from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import Column

import tests.shared.state_machine as state_machine

from supa.db.model import Reservation
from supa.job.provision import ProvisionJob, ReleaseJob


def test_provision_job_provision_confirmed(
    connection_id: Column, provisioning: None, get_stub: None, caplog: Any
) -> None:
    """Test ProvisionJob to transition to Provisioned."""
    provision_job = ProvisionJob(connection_id)
    provision_job.__call__()
    assert state_machine.is_provisioned(connection_id)
    assert state_machine.is_auto_start(connection_id)
    assert 'Added job "AutoStartJob"' in caplog.text


def test_provision_job_already_terminated(
    connection_id: Column, provisioning: None, terminated: None, get_stub: None, caplog: Any
) -> None:
    """Test ProvisionJob to return Error when reservation is already terminated."""
    provision_job = ProvisionJob(connection_id)
    provision_job.__call__()
    assert state_machine.is_provisioning(connection_id)
    assert "Reservation already terminated" in caplog.text
    assert "Not scheduling AutoStartJob or ActivateJob" in caplog.text


def test_provision_passed_start_time(connection_id: Column, provisioning: None, get_stub: None, caplog: Any) -> None:
    """Test ProvisionJob to transition to Provisioned and not start a AutoStartJob."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        reservation.start_time = datetime.now(timezone.utc) - timedelta(hours=1)
        reservation.end_time = datetime.now(timezone.utc) + timedelta(hours=1)
    provision_job = ProvisionJob(connection_id)
    provision_job.__call__()
    assert state_machine.is_provisioned(connection_id)
    assert 'Added job "ActivateJob"' in caplog.text


def test_provision_cannot_auto_start(
    connection_id: Column, provisioning: None, activated: None, get_stub: None, caplog: Any
) -> None:
    """Test ProvisionJob to return error when data plane cannot transition to auto start."""
    provision_job = ProvisionJob(connection_id)
    provision_job.__call__()
    assert state_machine.is_provisioning(connection_id)
    assert "Not scheduling AutoStartJo" in caplog.text
    assert "Can't auto_start_request when in Activated" in caplog.text


def test_provision_cannot_activate(
    connection_id: Column, provisioning: None, activate_failed: None, get_stub: None, caplog: Any
) -> None:
    """Test ProvisionJob to return error when data plane cannot transition to activating."""
    from supa.db.session import db_session

    with db_session() as session:
        reservation = session.query(Reservation).filter(Reservation.connection_id == connection_id).one()
        reservation.start_time = datetime.now(timezone.utc) - timedelta(hours=1)
        reservation.end_time = datetime.now(timezone.utc) + timedelta(hours=1)
    provision_job = ProvisionJob(connection_id)
    provision_job.__call__()
    assert state_machine.is_provisioning(connection_id)
    assert "Not scheduling ActivateJob" in caplog.text
    assert "Can't activate_request when in ActivateFailed" in caplog.text


def test_release_job_release_confirmed_auto_start(
    connection_id: Column, releasing: None, auto_start: None, auto_start_job: None, get_stub: None, caplog: Any
) -> None:
    """Test ReleaseJob to transition to Released and disable auto start of data plane."""
    release_job = ReleaseJob(connection_id)
    release_job.__call__()
    assert state_machine.is_released(connection_id)
    assert state_machine.is_deactivated(connection_id)
    assert "Canceled automatic enable of data plane at start time" in caplog.text


def test_release_job_release_confirmed_auto_end(
    connection_id: Column, releasing: None, auto_end: None, get_stub: None, caplog: Any
) -> None:
    """Test ReleaseJob to transition to Released and disable auto end of data plane."""
    release_job = ReleaseJob(connection_id)
    release_job.__call__()
    assert state_machine.is_released(connection_id)
    assert state_machine.is_deactivated(connection_id)
    assert "Canceled automatic disable of data plane at end time" in caplog.text


def test_release_job_release_confirmed_invalid_data_plane_state(
    connection_id: Column, releasing: None, activate_failed: None, get_stub: None, caplog: Any
) -> None:
    """Test ReleaseJob to transition to Released even when data plane is in activate failed state."""
    release_job = ReleaseJob(connection_id)
    release_job.__call__()
    assert state_machine.is_released(connection_id)
    assert "Can't deactivate_request when in ActivateFailed" in caplog.text
    assert "Not scheduling DeactivateJob" in caplog.text


def test_release_job_already_terminated(
    connection_id: Column, releasing: None, terminated: None, get_stub: None, caplog: Any
) -> None:
    """Test ReleaseJob to return Error when reservation is already terminated."""
    release_job = ReleaseJob(connection_id)
    release_job.__call__()
    assert state_machine.is_releasing(connection_id)
    assert "Reservation already terminated" in caplog.text
    assert "Not scheduling DeactivateJob" in caplog.text
