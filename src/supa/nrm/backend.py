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

from dataclasses import dataclass
from typing import List, Optional

import structlog
from structlog.stdlib import BoundLogger

from supa import settings
from supa.db.model import Topology

logger = structlog.get_logger(__name__)


@dataclass
class STP:
    """Properties of a Network Serivce Interface Service Termination Point.

    The topology property is a placeholder for future multiple topology support.
    """

    stp_id: str
    port_id: str
    vlans: str
    description: str = ""
    is_alias_in: str = ""
    is_alias_out: str = ""
    bandwidth: int = 1000000000
    enabled: bool = True
    topology: str = settings.topology


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
        self.log = logger

    def reserve(
        self,
        connection_id: str,
        bandwidth: int,
        src_port_id: str,
        src_vlan: int,
        dst_port_id: str,
        dst_vlan: int,
    ) -> Optional[str]:
        """Reserve resources in NRM."""
        self.log.info(
            "reserve resources in NRM", backend="no-op", primitive="reserve", connection_id=str(connection_id)
        )
        return None

    def reserve_timeout(
        self,
        connection_id: str,
        bandwidth: int,
        src_port_id: str,
        src_vlan: int,
        dst_port_id: str,
        dst_vlan: int,
        circuit_id: str,
    ) -> Optional[str]:
        """Reserve timeout resources in NRM."""
        self.log.info(
            "reserve timeout resources in NRM",
            backend="no-op",
            primitive="reserve_timeout",
            connection_id=str(connection_id),
        )
        return None

    def reserve_commit(
        self,
        connection_id: str,
        bandwidth: int,
        src_port_id: str,
        src_vlan: int,
        dst_port_id: str,
        dst_vlan: int,
        circuit_id: str,
    ) -> Optional[str]:
        """Reserve commit resources in NRM."""
        self.log.info(
            "reserve commit resources in NRM",
            backend="no-op",
            primitive="reserve_commit",
            connection_id=str(connection_id),
        )
        return None

    def reserve_abort(
        self,
        connection_id: str,
        bandwidth: int,
        src_port_id: str,
        src_vlan: int,
        dst_port_id: str,
        dst_vlan: int,
        circuit_id: str,
    ) -> Optional[str]:
        """Reserve abort resources in NRM."""
        self.log.info(
            "reserve abort resources in NRM",
            backend="no-op",
            primitive="reserve_abort",
            connection_id=str(connection_id),
        )
        return None

    def provision(
        self,
        connection_id: str,
        bandwidth: int,
        src_port_id: str,
        src_vlan: int,
        dst_port_id: str,
        dst_vlan: int,
        circuit_id: str,
    ) -> Optional[str]:
        """Provision resources in NRM."""
        self.log.info(
            "provision resources in NRM", backend="no-op", primitive="provision", connection_id=str(connection_id)
        )
        return None

    def release(
        self,
        connection_id: str,
        bandwidth: int,
        src_port_id: str,
        src_vlan: int,
        dst_port_id: str,
        dst_vlan: int,
        circuit_id: str,
    ) -> Optional[str]:
        """Release resources in NRM."""
        self.log.info(
            "release resources in NRM", backend="no-op", primitive="release", connection_id=str(connection_id)
        )
        return None

    def activate(
        self,
        connection_id: str,
        bandwidth: int,
        src_port_id: str,
        src_vlan: int,
        dst_port_id: str,
        dst_vlan: int,
        circuit_id: str,
    ) -> Optional[str]:
        """Activate resources in NRM."""
        self.log.info(
            "activate resources in NRM", backend="no-op", primitive="activate", connection_id=str(connection_id)
        )
        return None

    def deactivate(
        self,
        connection_id: str,
        bandwidth: int,
        src_port_id: str,
        src_vlan: int,
        dst_port_id: str,
        dst_vlan: int,
        circuit_id: str,
    ) -> Optional[str]:
        """Deactivate resources in NRM."""
        self.log.info(
            "deactivate resources in NRM", backend="no-op", primitive="deactivate", connection_id=str(connection_id)
        )
        return None

    def terminate(
        self,
        connection_id: str,
        bandwidth: int,
        src_port_id: str,
        src_vlan: int,
        dst_port_id: str,
        dst_vlan: int,
        circuit_id: str,
    ) -> Optional[str]:
        """Terminate resources in NRM."""
        self.log.info(
            "terminate resources in NRM", backend="no-op", primitive="terminate", connection_id=str(connection_id)
        )
        return None

    def topology(self) -> List[STP]:
        """Get the list of exposed STP's from NRM.

        Because this is a placeholder just return the STP's configured in the Topology table.
        """
        self.log.info("get topology from NRM", backend="no-op", primitive="topology")

        from supa.db.session import db_session

        stps: List[STP] = []
        with db_session() as session:
            for stp in session.query(Topology).all():
                stps.append(
                    STP(
                        stp_id=stp.stp_id,
                        port_id=stp.port_id,
                        vlans=stp.vlans,
                        description=stp.description,
                        is_alias_in=stp.is_alias_in,
                        is_alias_out=stp.is_alias_out,
                        bandwidth=stp.bandwidth,
                        enabled=stp.enabled,
                    )
                )
        return stps


"""Set backend to BaseBackend with methods that effectively do nothing,
except for the topology method that returns the STP's as configured in the Topology table.
The default backend can be overwritten by a custom backend
by specifying it in supa.env or on the command line of `supa serve`"""
backend = BaseBackend()
