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

from random import randint
from typing import Any, List
from uuid import UUID

from pydantic_settings import BaseSettings
from sqlalchemy import select

from supa.db.model import Connection
from supa.db.session import db_session
from supa.nrm.backend import STP, BaseBackend
from supa.util.find import find_file
from supa.util.nso import HTTPBasicAuth, NSOClient


class BackendSettings(BaseSettings):
    """Backend settings with default values.

    See also: the ``src/supa/nrm/backends/nso.env`` file
    """

    nso_url: str = "https://localhost:8443"
    nso_username: str
    nso_password: str
    nso_verify_ssl: bool


class Backend(BaseBackend):
    """NSO backend interface."""

    nso: NSOClient

    def __init__(self) -> None:
        """Load properties from 'nso.env'."""
        super(Backend, self).__init__()
        self.log.info("Loading NSO backend")
        self.backend_settings = BackendSettings(_env_file=(env_file := find_file("nso.env")))  # type: ignore[call-arg]

        self.log.info("Read backend properties", path=str(env_file))

        self.nso = NSOClient(
            base_url=self.backend_settings.nso_url,
            auth=HTTPBasicAuth(
                self.backend_settings.nso_username,
                self.backend_settings.nso_password,
            ),
            verify_ssl=self.backend_settings.nso_verify_ssl,
            logger=self.log,
        )

    def _service_create(
        self,
        circuit_id: str,
        src_port_id: str,
        src_vlan: int,
        dst_port_id: str,
        dst_vlan: int,
        bandwidth: int,
    ) -> Any:
        self.log.info("Create service in NSO")

        payload = {
            "nsi-circuit:nsi-circuit": [
                {
                    "circuit-id": circuit_id,
                    "admin-state": "in-service",
                    "src-port-id": {
                        "interface": src_port_id,
                        "vlan-id": src_vlan,
                    },
                    "dst-port-id": {
                        "interface": dst_port_id,
                        "vlan-id": dst_vlan,
                    },
                    "bandwidth": bandwidth,
                }
            ]
        }

        self.nso.post(
            path="/tailf-ncs:services/",
            payload=payload,
        )

    def _get_next_circuit_id(self) -> str:
        self.log.info("Get next circuit_id from SuPA DB")

        with db_session() as session:
            ids = session.execute(select(Connection.circuit_id).filter(Connection.circuit_id != None)).scalars().all()

        if ids:
            ids.sort(key=lambda x: int(x.split("_")[-1]))
            last_id = ids[-1]
            next_id = int(last_id.split("_")[-1]) + 1
            return f"NSI_L2VPN_{next_id}"
        else:
            return "NSI_L2VPN_10000"

    def _service_delete(self, circuit_id: str) -> None:
        self.log.info("Delete service in NSO")

        self.nso.delete(path=f"/tailf-ncs:services/nsi-circuit:nsi-circuit={circuit_id}")

    def _get_topology(self) -> List[STP]:
        self.log.info("Get topology from NSO")
        ports: List[STP] = []

        nso_stp = self.nso.post(path="/common:workflow/nsi-circuit:get-nsi-stp", payload={})
        self.log.debug("NSO STPs", nso_stp=nso_stp)

        for stp in nso_stp["nsi-circuit:output"]["stp-list"]:
            ports.append(
                STP(
                    stp_id=stp["stp-id"],
                    port_id=stp["port-id"],
                    vlans=stp["vlans"],
                    description=stp["description"],
                    bandwidth=stp["bandwidth"],
                    is_alias_in=stp["is-alias"],
                    is_alias_out=stp["is-alias"],
                )
            )
        return ports

    def activate(
        self,
        connection_id: UUID,
        bandwidth: int,
        src_port_id: str,
        src_vlan: int,
        dst_port_id: str,
        dst_vlan: int,
        circuit_id: str,
    ) -> str:
        """Activate resources in NRM."""
        self.log = self.log.bind(primitive="activate")
        self.log.debug(
            "Activate resource",
            connection_id=connection_id,
            bandwidth=bandwidth,
            src_port_id=src_port_id,
            src_vlan=src_vlan,
            dst_port_id=dst_port_id,
            dst_vlan=dst_vlan,
            circuit_id=circuit_id,
        )
        circuit_id = self._get_next_circuit_id()
        self.log.info("Setting circuit_id", circuit_id=circuit_id)
        self._service_create(circuit_id, src_port_id, src_vlan, dst_port_id, dst_vlan, bandwidth)
        return circuit_id

    def deactivate(
        self,
        connection_id: UUID,
        bandwidth: int,
        src_port_id: str,
        src_vlan: int,
        dst_port_id: str,
        dst_vlan: int,
        circuit_id: str,
    ) -> None:
        """Deactivate resources in NRM."""
        self.log = self.log.bind(primitive="deactivate")
        self.log.debug(
            "Deactivate resource",
            connection_id=connection_id,
            bandwidth=bandwidth,
            src_port_id=src_port_id,
            src_vlan=src_vlan,
            dst_port_id=dst_port_id,
            dst_vlan=dst_vlan,
            circuit_id=circuit_id,
        )
        self._service_delete(circuit_id)

    def topology(self) -> List[STP]:
        """Get exposed topology from NRM."""
        self.log = self.log.bind(primitive="topology")
        return self._get_topology()
