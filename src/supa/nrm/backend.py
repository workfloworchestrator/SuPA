#  Copyright 2022 SURF.
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

from typing import List

import structlog
from sqlalchemy.orm import aliased, session
from structlog.stdlib import BoundLogger

from supa import settings
from supa.db.model import Reservation, Topology

logger = structlog.get_logger(__name__)


class BaseBackend:
    """Default backend interface to Network Resource Manager.

    Backend interface between the following NSI primitives and the local NRM:

    reserve, reserve_timeout, reserve_commit, reserve_abort, provision, release, activate, deactivate and terminate

    The arguments for all functions are the same, for example the reserve():

    def reserve(
        self, connection_id: UUID, src_port_id: str, src_vlan: int, dst_port_id: str, dst_vlan: int, bandwidth: int
    ) -> None:
        ...

    If a function for a primitive is not defined the call the NRM will be skipped.
    """

    log: BoundLogger

    def __init__(self) -> None:
        """Initialize the BaseBackend."""
        self.log = logger.bind(backend="no-op")


"""Set backend to BaseBackend which effectively does nothing,
but this can be overwritten by a custom backend
as declared in supa.env or on the command line of `supa serve`"""
backend = BaseBackend()


class STP:
    """Properties of a Network Serivce Interface Service Termination Point.

    The topology property is a placeholder for future multiple topology support.
    """

    def __init__(
        self,
        topology: str = settings.network_type,
        stp_id: str = "",
        port_id: str = "",
        vlans: str = "",
        description: str = "",
        is_alias_in: str = "",
        is_alias_out: str = "",
        bandwidth: int = 1000000000,
        expose_in_topology: bool = True,
    ):
        """Initialise a Service Termination Point object."""
        self.topology: str = topology
        self.stp_id: str = stp_id
        self.port_id: str = port_id
        self.vlans: str = vlans
        self.description: str = description
        self.is_alias_in: str = is_alias_in
        self.is_alias_out: str = is_alias_out
        self.bandwidth: int = bandwidth
        self.expose_in_topology: bool = expose_in_topology


def get_topology() -> List[STP]:
    """Get topology from NRM returned as list of STP's."""
    backend.log = backend.log.bind(primitive="topology")
    try:
        return backend.topology()  # type: ignore[attr-defined,no-any-return]
    except (TypeError, AttributeError) as error:
        backend.log.warning("cannot get topology from NRM", error=error)
        return []


def call_backend(primitive: str, reservation: Reservation, database_session: session) -> None:
    """Call primitive of backend with reservation details as argument.

    We could have called the method directly on the class instance,
    but now we can log some additional information,
    resolve the src/dst stp_id to NRM port ID's,
    and we do not have to import `backend` locally
    to ensure it is initialized properly.
    """
    src_topology = aliased(Topology)
    dst_topology = aliased(Topology)
    src_port_id, dst_port_id = (
        database_session.query(src_topology.port_id, dst_topology.port_id).filter(
            Reservation.connection_id == reservation.connection_id,
            Reservation.src_stp_id == src_topology.stp_id,
            Reservation.dst_stp_id == dst_topology.stp_id,
        )
    ).one()
    # TODO change port_id from UUID to str to make it compatible with other NRM's
    backend.log = backend.log.bind(primitive=primitive, connection_id=str(reservation.connection_id))
    try:
        method = getattr(backend, primitive)
    except AttributeError:
        backend.log.debug("skipping call to NRM backend")
    else:
        if callable(method):
            backend.log.info(
                "calling NRM backend",
                src_port=str(src_port_id),
                src_vlan=reservation.src_selected_vlan,
                dst_port=str(dst_port_id),
                dst_vlan=reservation.dst_selected_vlan,
                bandwidth=reservation.bandwidth,
            )
            method(
                reservation.connection_id,
                src_port_id,
                reservation.src_selected_vlan,
                dst_port_id,
                reservation.dst_selected_vlan,
                reservation.bandwidth,
            )
        else:
            backend.log.warning("cannot call NRM backend with non-function")
