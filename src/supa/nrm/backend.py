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

import structlog
from sqlalchemy.orm import aliased, session
from structlog.stdlib import BoundLogger

from supa.db.model import Port, Reservation

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


def call_backend(primitive: str, reservation: Reservation, database_session: session) -> None:
    """Call method_name of backend with reservation as argument.

    We could have called the method directly on the class instance,
    but now we can log some additional information,
    resolve the src/dst port_name to NRM port ID's,
    and we do not have to import `backend` locally
    to ensure it is initialized properly.
    """
    src_port = aliased(Port)
    dst_port = aliased(Port)
    src_port_id, dst_port_id = (
        database_session.query(src_port.port_id, dst_port.port_id).filter(
            Reservation.connection_id == reservation.connection_id,
            Reservation.src_port == src_port.name,
            Reservation.dst_port == dst_port.name,
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
                str(src_port_id),
                reservation.src_selected_vlan,
                str(dst_port_id),
                reservation.dst_selected_vlan,
                reservation.bandwidth,
            )
        else:
            backend.log.warning("cannot call NRM backend with non-function")
