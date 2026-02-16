#  Copyright 2025 Internet2.
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

from typing import Any, List
from uuid import UUID

from httpx import BasicAuth
from nso_client import NSOClient, YangData
from pydantic_settings import BaseSettings
from sqlalchemy import select

from supa import settings
from supa.db.model import Connection
from supa.db.session import db_session
from supa.nrm.backend import STP, BaseBackend
from supa.util.find import find_file


class BackendSettings(BaseSettings):
    """Backend settings with default values.

    See also: the ``src/supa/nrm/backends/nso.env`` file
    """

    nso_url: str = "https://localhost:8443"
    nso_username: str
    nso_password: str
    nso_verify_ssl: bool
    nso_circuit_id_prefix: str = "NSI_L2VPN_"
    nso_circuit_id_start: int = 10000


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
            nso_url=self.backend_settings.nso_url,
            auth=BasicAuth(
                self.backend_settings.nso_username,
                self.backend_settings.nso_password,
            ),
            verify=self.backend_settings.nso_verify_ssl,
            logger=self.log,
        )

    def _service_create(
        self,
        circuit_id: str,
        topology: str,
        src_port_id: str,
        src_vlan: int,
        dst_port_id: str,
        dst_vlan: int,
        bandwidth: int,
    ) -> Any:
        self.log.info("Create service in NSO")

        payload: YangData = {
            "nsi-circuit:nsi-circuit": [
                {
                    "circuit-id": circuit_id,
                    "topology": topology,
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
            ids = (
                session.execute(select(Connection.circuit_id).filter(Connection.circuit_id.isnot(None))).scalars().all()
            )

        if ids:
            ids.sort(key=lambda x: int(x.split("_")[-1]))  # type: ignore[attr-defined]
            last_id = ids[-1]
            next_id = int(last_id.split("_")[-1]) + 1  # type: ignore[union-attr]
            return f"{self.backend_settings.nso_circuit_id_prefix}{next_id}"
        else:
            return f"{self.backend_settings.nso_circuit_id_prefix}{self.backend_settings.nso_circuit_id_start}"

    def _service_delete(self, circuit_id: str) -> None:
        self.log.info("Delete service in NSO")

        self.nso.delete(path=f"/tailf-ncs:services/nsi-circuit:nsi-circuit={circuit_id}")

    def _get_topology(self) -> List[STP]:
        self.log.info("Get topology from NSO")
        ports: List[STP] = []

        payload: YangData = {"input": {"name": settings.topology}}

        nso_stp = self.nso.post(path="/common:workflow/nsi-circuit:get-nsi-stp", payload=payload)
        self.log.debug("NSO STPs", nso_stp=nso_stp)

        if nso_stp is None:
            self.log.error(
                "NSO returned no data for topology request",
                topology=settings.topology,
                payload=payload,
            )
            raise ValueError(
                f"NSO returned no data for topology {settings.topology}. "
                "Check that the topology exists in NSO and the configuration is correct."
            )

        if "nsi-circuit:output" not in nso_stp or "stp-list" not in nso_stp.get("nsi-circuit:output", {}):
            self.log.error(
                "NSO response missing expected structure",
                nso_stp=nso_stp,
                topology=settings.topology,
            )
            raise ValueError(f"NSO response missing 'nsi-circuit:output' or 'stp-list'. Response: {nso_stp}")

        for stp in nso_stp["nsi-circuit:output"]["stp-list"]:
            ports.append(
                STP(
                    stp_id=stp["stp-id"],
                    port_id=stp["port-id"],
                    vlans=stp["vlans"],
                    description=stp.get("description"),
                    bandwidth=stp.get("bandwidth", 1000000000),
                    is_alias_in=stp.get("is-alias-in"),
                    is_alias_out=stp.get("is-alias-out"),
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
        topology = settings.topology
        self.log.info("Setting circuit_id", circuit_id=circuit_id)
        self._service_create(circuit_id, topology, src_port_id, src_vlan, dst_port_id, dst_vlan, bandwidth)
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
