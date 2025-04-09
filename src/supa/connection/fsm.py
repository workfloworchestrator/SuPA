#  Copyright 2020 SURF.
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
"""Define the three NSI Connection Service state machines.

The NSI Connection Service defines three state machines that,
together with the message processing functions (=coordinator functions in NSI parlance),
model the behaviour of the protocol.

They are:

- :class:`ReservationStateMachine` (RSM)
- :class:`ProvisionStateMachine` (PSM)
- :class:`LifecycleStateMachine` (LSM)

The state machines explicitly regulate the sequence in which messages are processed.
The CS messages are each assigned to one of the three state machines:
RSM, PSM and LSM.
When the first reserve request for a new Connection is received,
the function processing the reserve requests MUST coordinate the creation of the
RSM, PSM and LSM
state machines for that specific connection.

The RSM and LSM MUST be instantiated as soon as the first Connection request is received.

The PSM MUST be instantiated as soon as the first version of the reservation is committed.

"""

from typing import Any

import structlog
from statemachine import State, StateMachine
from structlog.stdlib import BoundLogger

logger = structlog.get_logger(__name__)


class SuPAStateMachine(StateMachine):
    """Add logging capabilities to StateMachine."""

    log: BoundLogger

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Log name of finite state machine and call __init__ of super class with original arguments."""
        self.log = logger.bind(fsm=self.__class__.__name__)
        super().__init__(*args, **kwargs)

    def on_enter_state(self, state: State) -> None:
        """Statemachine will call this function on every state transition."""
        if isinstance(state, State) and hasattr(self.model, "connection_id"):
            self.log.info("State transition", to_state=state.id, connection_id=str(self.model.connection_id))


class ReservationStateMachine(SuPAStateMachine):
    """Reservation State Machine.

    .. image:: /images/ReservationStateMachine.png
    """

    ReserveStart = State("ReserveStart", "RESERVE_START", initial=True)
    ReserveChecking = State("ReserveChecking", "RESERVE_CHECKING")
    ReserveHeld = State("ReserveHeld", "RESERVE_HELD")
    ReserveCommitting = State("ReserveCommitting", "RESERVE_COMMITTING")
    ReserveFailed = State("ReserveFailed", "RESERVE_FAILED")
    ReserveTimeout = State("ReserveTimeout", "RESERVE_TIMEOUT")
    ReserveAborting = State("ReserveAborting", "RESERVE_ABORTING")

    reserve_request = ReserveStart.to(ReserveChecking)
    reserve_confirmed = ReserveChecking.to(ReserveHeld)
    reserve_failed = ReserveChecking.to(ReserveFailed)
    reserve_abort_confirmed = ReserveAborting.to(ReserveStart)
    reserve_timeout_notification = ReserveHeld.to(ReserveTimeout)
    reserve_commit_request = ReserveHeld.to(ReserveCommitting) | ReserveTimeout.to(ReserveCommitting)
    reserve_commit_confirmed = ReserveCommitting.to(ReserveStart)
    reserve_commit_failed = ReserveCommitting.to(ReserveStart)
    reserve_abort_request = (
        ReserveFailed.to(ReserveAborting) | ReserveHeld.to(ReserveAborting) | ReserveTimeout.to(ReserveAborting)
    )


class ProvisionStateMachine(SuPAStateMachine):
    """Provision State Machine.

    .. image:: /images/ProvisionStateMachine.png
    """

    Released = State("Released", "RELEASED", initial=True)
    Provisioning = State("Provisioning", "PROVISIONING")
    Provisioned = State("Provisioned", "PROVISIONED")
    Releasing = State("Releasing", "RELEASING")

    provision_request = Released.to(Provisioning)
    provision_confirmed = Provisioning.to(Provisioned)
    release_request = Provisioned.to(Releasing)
    release_confirmed = Releasing.to(Released)


class LifecycleStateMachine(SuPAStateMachine):
    """Lifecycle State Machine.

    .. image:: /images/LifecycleStateMachine.png
    """

    Created = State("Created", "CREATED", initial=True)
    Failed = State("Failed", "FAILED")
    Terminating = State("Terminating", "TERMINATING")
    PassedEndTime = State("PassedEndTime", "PASSED_END_TIME")
    Terminated = State("Terminated", "TERMINATED", final=True)

    forced_end_notification = Created.to(Failed)
    terminate_request = Created.to(Terminating) | PassedEndTime.to(Terminating) | Failed.to(Terminating)
    endtime_event = Created.to(PassedEndTime)
    terminate_confirmed = Terminating.to(Terminated)


class DataPlaneStateMachine(SuPAStateMachine):
    """DataPlane State Machine.

    .. image:: /images/DataPlaneStateMachine.png
    """

    Deactivated = State("Deactivated", "DEACTIVATED", initial=True)
    AutoStart = State("AutoStart", "AUTO_START")
    Activating = State("Activating", "ACTIVATING")
    Activated = State("Activated", "ACTIVATED")
    AutoEnd = State("AutoEnd", "AUTO_END")
    Deactivating = State("Deactivating", "DEACTIVATING")
    ActivateFailed = State("ActivateFailed", "ACTIVATE_FAILED", final=True)
    DeactivateFailed = State("DeactivateFailed", "DEACTIVATE_FAILED", final=True)
    Unhealthy = State("Unhealthy", "UNHEALTHY", final=True)

    auto_start_request = Deactivated.to(AutoStart)
    activate_request = Deactivated.to(Activating) | AutoStart.to(Activating)
    activate_confirmed = Activating.to(Activated)
    auto_end_request = Activated.to(AutoEnd)
    cancel_auto_end_request = AutoEnd.to(Activated)
    deactivate_request = Activated.to(Deactivating) | AutoEnd.to(Deactivating) | AutoStart.to(Deactivated)
    deactivate_confirm = Deactivating.to(Deactivated)
    activate_failed = Activating.to(ActivateFailed)
    deactivate_failed = Deactivating.to(DeactivateFailed)
    not_healthy = Activated.to(Unhealthy)


if __name__ == "__main__":  # pragma: no cover
    # If you have Graphviz and the corresponding Python package ``graphviz`` installed,
    # generating a graphical representation of the state machines is as easy as running this module.
    # The generated graphs are not the most beautiful
    # or best layed out ones,
    # but do provide the means to visually inspect the state machine definitions.
    # In addition we now have images that we can include in our documentation.
    # That is,
    # by the way,
    # the reason the images are generated in the docs/images folder of this project
    from graphviz import Digraph

    from supa import get_project_root

    output_path = get_project_root() / "docs" / "images"

    def plot_fsm(fsm: StateMachine, name: str) -> None:
        """Generate image that visualizes a state machine."""
        dg = Digraph(name=name, comment=name)
        for s in fsm.states:
            for t in s.transitions:
                dg.edge(t.source.value, t.target.value, label=t.event)
        dg.render(filename=name, directory=output_path, cleanup=True, format="png")

    plot_fsm(ReservationStateMachine(), "ReservationStateMachine")
    plot_fsm(ProvisionStateMachine(), "ProvisionStateMachine")
    plot_fsm(LifecycleStateMachine(), "LifecycleStateMachine")
    plot_fsm(DataPlaneStateMachine(), "DataPlaneStateMachine")
