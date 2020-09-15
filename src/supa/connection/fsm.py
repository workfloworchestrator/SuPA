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
- :class:`ProvisioningStateMachine` (PSM)
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
from statemachine import State, StateMachine


class ReservationStateMachine(StateMachine):
    """Reservation State Machine.

    .. image:: /images/ReservationStateMachine.png
    """

    start = State("Start", initial=True)
    checking = State("Checking")
    held = State("Held")
    committing = State("Committing")
    failed = State("Failed")
    timeout = State("Timeout")
    aborting = State("Aborting")

    reserve_request = start.to(checking)
    reserve_confirmed = checking.to(held)
    reserve_failed = checking.to(failed)
    reserve_abort_request = failed.to(aborting) | held.to(aborting)
    reserve_abort_confirmed = aborting.to(start)
    reserve_timeout_notification = held.to(timeout)
    reserve_commit_request = held.to(committing) | timeout.to(committing)
    reserve_commit_confirmed = committing.to(start)
    reserve_commit_failed = committing.to(start)


class ProvisioningStateMachine(StateMachine):
    """Provisioning State Machine.

    .. image:: /images/ProvisioningStateMachine.png
    """

    released = State("Released", initial=True)
    provisioning = State("Provisioning")
    provisioned = State("Provisioned")
    releasing = State("Releasing")

    provision_request = released.to(provisioning)
    provision_confirmed = provisioning.to(provisioned)
    release_request = provisioned.to(releasing)
    release_confirmed = releasing.to(released)


class LifecycleStateMachine(StateMachine):
    """Lifecycle State Machine.

    .. image:: /images/LifecycleStateMachine.png
    """

    created = State("Created", initial=True)
    failed = State("Failed")
    terminating = State("Terminating")
    passed_endtime = State("PassedEndTime")
    terminated = State("Terminated")

    forced_end_notification = created.to(failed)
    terminate_request = created.to(terminating) | passed_endtime.to(terminating) | failed.to(terminating)
    endtime_event = created.to(passed_endtime)
    terminate_confirmed = terminating.to(terminated)


if __name__ == "__main__":
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
                dg.edge(t.source.name, t.destinations[0].name, label=t.identifier)
        dg.render(filename=name, directory=output_path, cleanup=True, format="png")

    plot_fsm(ReservationStateMachine(), "ReservationStateMachine")
    plot_fsm(ProvisioningStateMachine(), "ProvisioningStateMachine")
    plot_fsm(LifecycleStateMachine(), "LifecycleStateMachine")
