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

# from uuid import UUID


# from typing import List
# from uuid import UUID

from pydantic_settings import BaseSettings

from supa.nrm.backend import BaseBackend

# from supa.nrm.backend import STP


class BackendSettings(BaseSettings):
    """Backend settings with default values.

    See also: the ``src/supa/nrm/backends/example.env`` file
    """

    target_host: str = "localhost"
    target_port: int = 80


backend_settings = BackendSettings(_env_file="src/supa/nrm/backends/example.env")  # type: ignore[call-arg]


class Backend(BaseBackend):
    """Example backend interface.

    Only implement the calls that are needed to interface with the NRM.
    """

    # def reserve(
    #     self,
    #     connection_id: UUID,
    #     bandwidth: int,
    #     src_port_id: str,
    #     src_vlan: int,
    #     dst_port_id: str,
    #     dst_vlan: int,
    # ) -> None:
    #     """Reserve resources in NRM."""
    #     self.log.info(
    #         "reserve resources in NRM",
    #         target_host=backend_settings.target_host,
    #         target_port=backend_settings.target_port,
    #     )
    #
    # def reserve_timeout(
    #     self,
    #     connection_id: UUID,
    #     bandwidth: int,
    #     src_port_id: str,
    #     src_vlan: int,
    #     dst_port_id: str,
    #     dst_vlan: int,
    #     circuit_id: str,
    # ) -> None:
    #     """Reserve timeout resources in NRM."""
    #
    # def reserve_commit(
    #     self,
    #     connection_id: UUID,
    #     bandwidth: int,
    #     src_port_id: str,
    #     src_vlan: int,
    #     dst_port_id: str,
    #     dst_vlan: int,
    #     circuit_id: str,
    # ) -> None:
    #     """Reserve commit resources in NRM."""
    #
    # def reserve_abort(
    #     self,
    #     connection_id: UUID,
    #     bandwidth: int,
    #     src_port_id: str,
    #     src_vlan: int,
    #     dst_port_id: str,
    #     dst_vlan: int,
    #     circuit_id: str,
    # ) -> None:
    #     """Reserve abort resources in NRM."""
    #
    # def provision(
    #     self,
    #     connection_id: UUID,
    #     bandwidth: int,
    #     src_port_id: str,
    #     src_vlan: int,
    #     dst_port_id: str,
    #     dst_vlan: int,
    #     circuit_id: str,
    # ) -> None:
    #     """Provision resources in NRM."""
    #
    # def release(
    #     self,
    #     connection_id: UUID,
    #     bandwidth: int,
    #     src_port_id: str,
    #     src_vlan: int,
    #     dst_port_id: str,
    #     dst_vlan: int,
    #     circuit_id: str,
    # ) -> None:
    #     """Release resources in NRM."""
    #
    # def activate(
    #     self,
    #     connection_id: UUID,
    #     bandwidth: int,
    #     src_port_id: str,
    #     src_vlan: int,
    #     dst_port_id: str,
    #     dst_vlan: int,
    #     circuit_id: str,
    # ) -> None:
    #     """Activate resources in NRM."""
    #
    # def deactivate(
    #     self,
    #     connection_id: UUID,
    #     bandwidth: int,
    #     src_port_id: str,
    #     src_vlan: int,
    #     dst_port_id: str,
    #     dst_vlan: int,
    #     circuit_id: str,
    # ) -> None:
    #     """Deactivate resources in NRM."""
    #
    # def terminate(
    #     self,
    #     connection_id: UUID,
    #     bandwidth: int,
    #     src_port_id: str,
    #     src_vlan: int,
    #     dst_port_id: str,
    #     dst_vlan: int,
    #     circuit_id: str,
    # ) -> None:
    #     """Terminate resources in NRM."""
    #
    # def get_topology(self) -> List[STP]:
    #     """Get the list of exposed STP's from NRM."""
