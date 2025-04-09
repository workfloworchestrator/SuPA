import datetime
from typing import Any
from uuid import UUID

import tests.shared.state_machine as state_machine

from supa import settings
from supa.job.lifecycle import HealthCheckJob, TerminateJob
from supa.util.timestamp import current_timestamp


def test_terminate_job_auto_start(
    connection_id: UUID,
    connection: None,
    terminating: None,
    auto_start: None,
    auto_start_job: None,
    get_stub: None,
    caplog: Any,
) -> None:
    """Test TerminateJob to transition to Terminated and transition data plane to Deactivated."""
    terminate_job = TerminateJob(connection_id)
    terminate_job.__call__()
    assert state_machine.is_deactivated(connection_id)
    assert state_machine.is_terminated(connection_id)
    assert "Terminate reservation" in caplog.text
    assert "Cancel auto start" in caplog.text


def test_terminate_job_auto_end(
    connection_id: UUID, connection: None, terminating: None, auto_end: None, get_stub: None, caplog: Any
) -> None:
    """Test TerminateJob to transition to Terminated, add DeactivateJob and canceling AutoEndJob."""
    terminate_job = TerminateJob(connection_id)
    terminate_job.__call__()
    # assert state_machine.is_deactivating(connection_id) # FIXME need DeactivateJob monkey patch
    assert state_machine.is_terminated(connection_id)
    assert "Terminate reservation" in caplog.text
    assert "Cancel auto end" in caplog.text
    assert "Schedule deactivate" in caplog.text


def test_terminate_job_activated(
    connection_id: UUID, connection: None, terminating: None, activated: None, get_stub: None, caplog: Any
) -> None:
    """Test TerminateJob to transition to Terminated and add DeactivateJob."""
    terminate_job = TerminateJob(connection_id)
    terminate_job.__call__()
    # assert state_machine.is_deactivating(connection_id) # FIXME need DeactivateJob monkey patch
    assert state_machine.is_terminated(connection_id)
    assert "Terminate reservation" in caplog.text
    assert "Cancel auto end" not in caplog.text
    assert "Schedule deactivate" in caplog.text


def test_terminate_job_recover(connection_id: UUID, terminating: None, get_stub: None, caplog: Any) -> None:
    """Test TerminateJob to recover reservations in state Terminating."""
    terminate_job = TerminateJob(connection_id)
    job_list = terminate_job.recover()
    assert len(job_list) == 1
    assert job_list[0].connection_id == connection_id
    assert state_machine.is_terminating(connection_id)
    msgs = [
        logrecord.msg
        for logrecord in caplog.records
        if "job" in logrecord.msg and logrecord.msg["job"] == "TerminateJob"
    ]
    assert len(msgs) == 1
    assert msgs[0]["connection_id"] == str(connection_id)
    assert msgs[0]["event"] == "Recovering job"


def test_terminate_job_trigger(connection_id: UUID, caplog: Any) -> None:
    """Test TerminateJob to return trigger to run immediately."""
    terminate_job = TerminateJob(connection_id)
    job_trigger = terminate_job.trigger()
    assert current_timestamp() - job_trigger.run_date < datetime.timedelta(seconds=5)  # more or less now


def filter_caplog_records(caplog: Any, msg: str, value: str) -> list[Any]:
    """Return log records where `msg` exactly matches `value`."""
    return [record for record in caplog.records if record.msg[msg] == value]


def test_health_check_job_healthy_activated(
    connection_id: UUID, connection: None, provisioned: None, activated: None, caplog: Any
) -> None:
    """Test HealthCheckJob to verify one healthy activated connection."""
    health_check_job = HealthCheckJob()
    health_check_job.__call__()
    records = filter_caplog_records(caplog, "event", "Connection health check")
    assert len(records) == 1
    assert records[0].msg["job"] == "HealthCheckJob"
    records = filter_caplog_records(caplog, "event", "Health check resources in NRM")
    assert len(records) == 1
    assert records[0].msg["backend"] == "no-op"
    assert records[0].msg["primitive"] == "health_check"
    assert records[0].msg["connection_id"] == str(connection_id)


def test_health_check_job_healthy_auto_end(
    connection_id: UUID, connection: None, provisioned: None, auto_end: None, caplog: Any
) -> None:
    """Test HealthCheckJob to verify one healthy auto end connection."""
    health_check_job = HealthCheckJob()
    health_check_job.__call__()
    records = filter_caplog_records(caplog, "event", "Connection health check")
    assert len(records) == 1
    assert records[0].msg["job"] == "HealthCheckJob"
    records = filter_caplog_records(caplog, "event", "Health check resources in NRM")
    assert len(records) == 1
    assert records[0].msg["backend"] == "no-op"
    assert records[0].msg["primitive"] == "health_check"
    assert records[0].msg["connection_id"] == str(connection_id)


def test_health_check_job_unhealthy_activated(
    connection_id: UUID,
    connection: None,
    provisioned: None,
    activated: None,
    caplog: Any,
    monkeypatch: Any,
    get_stub: None,
) -> None:
    """Test HealthCheckJob for one unhealthy connection."""
    from supa.nrm.backend import BaseBackend

    def mocked_health_check(
        self: HealthCheckJob,
        connection_id: UUID,
        bandwidth: int,
        src_port_id: str,
        src_vlan: int,
        dst_port_id: str,
        dst_vlan: int,
        circuit_id: str,
    ) -> bool:
        return False

    monkeypatch.setattr(BaseBackend, "health_check", mocked_health_check)

    health_check_job = HealthCheckJob()
    health_check_job.__call__()
    records = filter_caplog_records(caplog, "event", "Connection health check")
    assert len(records) == 1
    assert records[0].msg["job"] == "HealthCheckJob"
    records = filter_caplog_records(caplog, "event", "State transition")
    assert len(records) == 2
    assert records[0].msg["fsm"] == "LifecycleStateMachine"
    assert records[0].msg["to_state"] == "Failed"
    assert records[0].msg["connection_id"] == str(connection_id)
    assert records[1].msg["fsm"] == "DataPlaneStateMachine"
    assert records[1].msg["to_state"] == "Unhealthy"
    assert records[1].msg["connection_id"] == str(connection_id)


def test_health_check_job_unexpected_error_activated(
    connection_id: UUID,
    connection: None,
    provisioned: None,
    activated: None,
    caplog: Any,
    monkeypatch: Any,
    get_stub: None,
) -> None:
    """Test HealthCheckJob for one verify connection with an unexpected error."""
    from supa.nrm.backend import BaseBackend

    def mocked_health_check(
        self: HealthCheckJob,
        connection_id: UUID,
        bandwidth: int,
        src_port_id: str,
        src_vlan: int,
        dst_port_id: str,
        dst_vlan: int,
        circuit_id: str,
    ) -> bool:
        raise Exception

    monkeypatch.setattr(BaseBackend, "health_check", mocked_health_check)

    health_check_job = HealthCheckJob()
    health_check_job.__call__()
    records = filter_caplog_records(caplog, "event", "Connection health check")
    assert len(records) == 1
    assert records[0].levelname == "DEBUG"
    assert records[0].msg["job"] == "HealthCheckJob"
    records = filter_caplog_records(caplog, "event", "Unexpected error occurred.")
    assert len(records) == 1
    assert records[0].msg["job"] == "HealthCheckJob"
    records = filter_caplog_records(caplog, "event", "Error getting connection health from NRM")
    assert len(records) == 1
    assert records[0].msg["job"] == "HealthCheckJob"
    assert records[0].msg["connection_id"] == str(connection_id)


def test_health_check_job_recover(connection_id: UUID, provisioned: None, activated: None) -> None:
    """Test HealthCheckJob to recover zero jobs."""
    health_check_job = HealthCheckJob()
    job_list = health_check_job.recover()
    assert len(job_list) == 0


def test_health_check_job_trigger(caplog: Any) -> None:
    """Test TerminateJob to return trigger to run immediately."""
    health_check_job = HealthCheckJob()
    job_trigger = health_check_job.trigger()
    assert job_trigger.interval.seconds == settings.backend_health_check_interval
    assert job_trigger.timezone == datetime.timezone.utc
    assert job_trigger.end_date is None
    assert current_timestamp() + datetime.timedelta(
        seconds=settings.backend_health_check_interval
    ) - job_trigger.start_date < datetime.timedelta(
        seconds=5
    )  # with a marging of 5 seconds
