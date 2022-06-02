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
from time import sleep
from typing import Any, List
from uuid import UUID

from pydantic import BaseSettings
from requests import get, post
from requests.auth import HTTPBasicAuth
from requests.exceptions import ConnectionError, HTTPError
from structlog.stdlib import BoundLogger

from supa.connection.error import GenericRmError
from supa.job.shared import NsiException
from supa.nrm.backend import STP, BaseBackend
from supa.util.find import find_file


class BackendSettings(BaseSettings):
    """Backend settings with default values.

    See also: the ``src/supa/nrm/backends/surf.env`` file
    """

    host: str = "http://localhost"
    oauth2_active: bool = False
    oidc_url: str = ""
    oidc_user: str = ""
    oidc_password: str = ""
    create_workflow_name: str = ""
    terminate_workflow_name: str = ""
    customer_id: str = ""
    product_id: str = ""


class Backend(BaseBackend):
    """SURF backend interface to workflow orchestrator."""

    def __init__(self) -> None:
        """Load properties from 'surf.env'."""
        super(Backend, self).__init__()
        self.backend_settings = BackendSettings(_env_file=(env_file := find_file("surf.env")))
        self.log.info("Read backend properties", path=str(env_file))

    def _retrieve_access_token(self) -> str:
        access_token = ""  # noqa: S105
        if self.backend_settings.oauth2_active:
            self.log.info("retrieve access_token")
            token = post(
                self.backend_settings.oidc_url,
                auth=HTTPBasicAuth(self.backend_settings.oidc_user, self.backend_settings.oidc_password),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data="grant_type=client_credentials",
            )
            if token:
                if token.status_code > 210:
                    try:
                        token.raise_for_status()
                    except HTTPError as http_err:
                        self.log.warning("unable to authenticate", reason=str(http_err))
                        raise NsiException(GenericRmError, str(http_err)) from http_err
                else:
                    access_token = token.json()["access_token"]
        self.log.debug("workflow credentials", access_token=access_token, host=self.backend_settings.host)
        return access_token

    def _workflow_create(
        self, connection_id: UUID, src_port_id: str, src_vlan: int, dst_port_id: str, dst_vlan: int, bandwidth: int
    ) -> Any:
        self.log.info("start workflow create")
        access_token = self._retrieve_access_token()
        try:
            result = post(
                f"{self.backend_settings.host}/api/processes/{self.backend_settings.create_workflow_name}",
                headers={"Authorization": f"bearer {access_token}"},
                json=[
                    {"product": self.backend_settings.product_id},
                    {
                        "organisation": self.backend_settings.customer_id,
                        "service_ports": [
                            {
                                "subscription_id": src_port_id,
                                "vlan": str(src_vlan),
                            },
                            {"subscription_id": dst_port_id, "vlan": dst_vlan},
                        ],
                        "service_speed": bandwidth,
                        "speed_policer": True,
                        "remote_port_shutdown": False,
                    },
                ],
            )
        except ConnectionError as con_err:
            self.log.warning("call to orchestrator failed", reason=str(con_err))
            raise NsiException(GenericRmError, str(con_err)) from con_err
        if result.status_code > 210:
            try:
                result.raise_for_status()
            except HTTPError as http_err:
                self.log.warning("workflow failed", reason=str(http_err))
                raise NsiException(GenericRmError, str(http_err)) from http_err
        return result.json()

    def _workflow_terminate(self, subscription_id: str) -> Any:
        self.log.info("start workflow terminate")
        access_token = self._retrieve_access_token()
        try:
            result = post(
                f"{self.backend_settings.host}/api/processes/{self.backend_settings.terminate_workflow_name}",
                headers={
                    "Authorization": f"bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json=[{"subscription_id": subscription_id}, {}],
            )
        except ConnectionError as con_err:
            self.log.warning("call to orchestrator failed", reason=str(con_err))
            raise NsiException(GenericRmError, str(con_err)) from con_err
        if result.status_code > 210:
            try:
                result.raise_for_status()
            except HTTPError as http_err:
                self.log.warning("workflow failed", reason=str(http_err))
                raise NsiException(GenericRmError, str(http_err)) from http_err
        return result.json()

    def _add_note(self, connection_id: UUID, subscription_id: str) -> None:
        self.log.info("start workflow modify note")
        access_token = self._retrieve_access_token()
        try:
            self.log.info("adding connection id to note of subscription")
            result = post(
                f"{self.backend_settings.host}/api/processes/modify_note",
                headers={
                    "Authorization": f"bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json=[
                    {"subscription_id": subscription_id},
                    {"note": f"NSI connectionId {connection_id}"},
                ],
            )
        except ConnectionError as con_err:
            self.log.warning("call to orchestrator failed", reason=str(con_err))
            raise NsiException(GenericRmError, str(con_err)) from con_err
        if result.status_code > 210:
            try:
                result.raise_for_status()
            except HTTPError as http_err:
                self.log.warning("failed to add note to subscription", reason=str(http_err))
                raise NsiException(GenericRmError, str(http_err)) from http_err

    def _get_process_info(self, process_id: str) -> Any:
        access_token = self._retrieve_access_token()
        process = get(
            f"{self.backend_settings.host}/api/processes/{process_id}",
            headers={"Authorization": f"bearer {access_token}"},
        )
        self.log.debug("process status", process_status=process.json()["status"])
        return process.json()

    def _wait_for_completion(self, process_id: str) -> None:
        log = self.log.bind(process_id=process_id)
        sleep(1)
        while (info := self._get_process_info(process_id))["status"] == "running":
            log.info("waiting on workflow process to finish")
            sleep(3)
        log.info("workflow process finished")
        if info["status"] != "completed":
            log.warning("workflow process failed", reason=info["failed_reason"])
            raise NsiException(GenericRmError, info["failed_reason"]) from None

    def _get_subscription_id(self, process_id: str) -> str:
        access_token = self._retrieve_access_token()
        process = get(
            f"{self.backend_settings.host}/api/processes/{process_id}",
            headers={"Authorization": f"bearer {access_token}"},
        )
        self.log.debug("process status", process_status=process.json()["status"])
        return str(process.json()["current_state"]["subscription"]["subscription_id"])

    def _get_nsi_stp_subscriptions(self) -> Any:
        access_token = self._retrieve_access_token()
        nsi_stp_subscriptions = get(
            f"{self.backend_settings.host}/api/subscriptions/?filter=status,active,tag,NSISTP-NSISTPNL",
            headers={"Authorization": f"bearer {access_token}"},
        )
        if nsi_stp_subscriptions.status_code != 200:
            try:
                nsi_stp_subscriptions.raise_for_status()
            except HTTPError as http_err:
                self.log.warning("failed to fetch NSISTP subscriptions", reason=str(http_err))
                raise NsiException(GenericRmError, str(http_err)) from http_err
        return nsi_stp_subscriptions.json()

    def _get_topology(self) -> List[STP]:
        self.log.debug("get topology from NRM")
        access_token = self._retrieve_access_token()
        ports: List[STP] = []
        for nsi_stp_sub in self._get_nsi_stp_subscriptions():
            nsi_stp_dm = get(
                f"{self.backend_settings.host}/api/subscriptions/domain-model/{nsi_stp_sub['subscription_id']}",
                headers={"Authorization": f"bearer {access_token}"},
            )
            if nsi_stp_dm.status_code != 200:
                try:
                    nsi_stp_dm.raise_for_status()
                except HTTPError as http_err:
                    self.log.warning(
                        "failed to fetch NSISTP domain model",
                        reason=str(http_err),
                        nsi_stp_subscription_id=nsi_stp_sub["subscription_id"],
                    )
                    raise NsiException(GenericRmError, str(http_err)) from http_err
            else:
                nsi_stp_dict = nsi_stp_dm.json()
                ports.append(
                    STP(
                        topology=nsi_stp_dict["settings"]["topology"],
                        stp_id=nsi_stp_dict["settings"]["stp_id"],
                        port_id=nsi_stp_dict["settings"]["sap"]["port_subscription_id"],
                        vlans=nsi_stp_dict["settings"]["sap"]["vlanrange"],
                        description=nsi_stp_dict["settings"]["stp_description"],
                        is_alias_in=nsi_stp_dict["settings"]["is_alias_in"],
                        is_alias_out=nsi_stp_dict["settings"]["is_alias_out"],
                        bandwidth=1000000000,  # TODO return NSISTP bandwidth once implemented
                        enabled=nsi_stp_dict["settings"]["expose_in_topology"],
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
        self.log: BoundLogger = self.log.bind(primitive="activate", connection_id=str(connection_id))
        process = self._workflow_create(connection_id, src_port_id, src_vlan, dst_port_id, dst_vlan, bandwidth)
        self._wait_for_completion(process["id"])
        subscription_id = self._get_subscription_id(process["id"])
        self.log = self.log.bind(subscription_id=subscription_id)
        self._add_note(connection_id, subscription_id)
        return subscription_id

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
        self.log = self.log.bind(primitive="deactivate", subscription_id=circuit_id, connection_id=str(connection_id))
        process = self._workflow_terminate(circuit_id)
        self._wait_for_completion(process["id"])

    def topology(self) -> List[STP]:
        """Get exposed topology from NRM."""
        self.log = self.log.bind(primitive="topology")
        return self._get_topology()
