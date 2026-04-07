"""Tests covering code paths that use statemachine APIs changing in v3.

These tests pin current behavior of `current_state` comparisons in:
- `src/supa/job/reserve.py:510-511` (data_plane_active in ReserveCommitJob)
"""

from typing import Any
from uuid import UUID

import tests.shared.state_machine as state_machine
from supa.job.reserve import ReserveCommitJob


def test_reserve_commit_modified_change_bandwidth_auto_end(
    connection_id: UUID,
    connection: None,
    reserve_committing: None,
    modified_bandwidth_auto_end: None,
    get_stub: None,
    caplog: Any,
) -> None:
    """Test ReserveCommitJob calls modify() when data plane is in AutoEnd state.

    Covers the `dpsm.current_state == DataPlaneStateMachine.AutoEnd` branch
    in the data_plane_active check at reserve.py:511.
    """
    reserve_commit_job = ReserveCommitJob(connection_id)
    reserve_commit_job.__call__()
    assert state_machine.is_reserve_start(connection_id)
    assert "modify bandwidth on connection" in caplog.text
    assert "Modify resources in NRM" in caplog.text


def test_reserve_commit_modified_change_bandwidth_not_active(
    connection_id: UUID,
    connection: None,
    reserve_committing: None,
    modified_bandwidth_deactivated: None,
    get_stub: None,
    caplog: Any,
) -> None:
    """Test ReserveCommitJob does NOT call modify() when data plane is Deactivated.

    Covers the negative case where data_plane_active is False at reserve.py:510-511.
    """
    reserve_commit_job = ReserveCommitJob(connection_id)
    reserve_commit_job.__call__()
    assert state_machine.is_reserve_start(connection_id)
    assert "modify bandwidth on connection" not in caplog.text
