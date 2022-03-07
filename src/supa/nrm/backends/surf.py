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
from typing import Any
from uuid import UUID

from pydantic import BaseSettings
from requests import get, post
from requests.auth import HTTPBasicAuth
from requests.exceptions import ConnectionError, HTTPError

from supa.connection.error import GenericRmError
from supa.job.shared import NsiException
from supa.nrm.backend import BaseBackend


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


backend_settings = BackendSettings(_env_file="src/supa/nrm/backends/surf.env")


class Backend(BaseBackend):
    """SURF backend interface to workflow orchestrator."""

    def _retrieve_access_token(self) -> str:
        access_token = ""  # noqa: S105
        if backend_settings.oauth2_active:
            self.log.info("retrieve access_token")
            token = post(
                backend_settings.oidc_url,
                auth=HTTPBasicAuth(backend_settings.oidc_user, backend_settings.oidc_password),
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
        self.log.debug("workflow credentials", access_token=access_token, host=backend_settings.host)
        return access_token

    def _workflow_create(
        self, connection_id: UUID, src_port_id: str, src_vlan: int, dst_port_id: str, dst_vlan: int, bandwidth: int
    ) -> Any:
        self.log.info("start workflow create")
        access_token = self._retrieve_access_token()
        try:
            result = post(
                f"{backend_settings.host}/api/processes/{backend_settings.create_workflow_name}",
                headers={"Authorization": f"bearer {access_token}"},
                json=[
                    {"product": backend_settings.product_id},
                    {
                        "organisation": backend_settings.customer_id,
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

    def _workflow_terminate(
        self, connection_id: UUID, src_port_id: str, src_vlan: int, dst_port_id: str, dst_vlan: int, bandwidth: int
    ) -> Any:
        self.log.info("start workflow terminate")
        access_token = self._retrieve_access_token()
        light_path = get(
            f"{backend_settings.host}/api/surf/subscriptions/nsi",
            headers={"Authorization": f"bearer {access_token}"},
            params={  # type: ignore[arg-type]
                "port_subscription_id_1": src_port_id,
                "vlan_1": src_vlan,
                "port_subscription_id_2": dst_port_id,
                "vlan_2": dst_vlan,
            },
        )
        if light_path.status_code != 200:
            try:
                light_path.raise_for_status()
            except HTTPError as http_err:
                self.log.warning("failed to find matching subscription", reason=str(http_err))
                raise NsiException(GenericRmError, str(http_err)) from http_err
        else:
            self.log.info("found matching subscription", surbscription_id=light_path.json()["subscription_id"])
            try:
                result = post(
                    f"{backend_settings.host}/api/processes/{backend_settings.terminate_workflow_name}",
                    headers={
                        "Authorization": f"bearer {access_token}",
                        "Content-Type": "application/json",
                    },
                    json=[{"subscription_id": light_path.json()["subscription_id"]}, {}],
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

    def _modify_note(
        self, connection_id: UUID, src_port_id: str, src_vlan: int, dst_port_id: str, dst_vlan: int, bandwidth: int
    ) -> None:
        self.log.info("start workflow modify note")
        access_token = self._retrieve_access_token()
        light_path = get(
            f"{backend_settings.host}/api/surf/subscriptions/nsi",
            headers={"Authorization": f"bearer {access_token}"},
            params={  # type: ignore[arg-type]
                "port_subscription_id_1": src_port_id,
                "vlan_1": src_vlan,
                "port_subscription_id_2": dst_port_id,
                "vlan_2": dst_vlan,
            },
        )
        if light_path.status_code == 200:
            self.log.info(
                "adding connection id to note of subscription", surbscription_id=light_path.json()["subscription_id"]
            )
            post(
                f"{backend_settings.host}/api/processes/modify_note",
                headers={
                    "Authorization": f"bearer {access_token}",
                    "Content-Type": "application/json",
                },
                json=[
                    {"subscription_id": light_path.json()["subscription_id"]},
                    {"note": f"NSI connectionId {connection_id}"},
                ],
            )
        else:
            try:
                light_path.raise_for_status()
            except HTTPError as http_err:
                self.log.warning("failed to find matching subscription", reason=str(http_err))
                raise NsiException(GenericRmError, str(http_err)) from http_err

    def _check_process_status(self, process_id: str) -> Any:
        access_token = self._retrieve_access_token()
        process = get(
            f"{backend_settings.host}/api/processes/{process_id}",
            headers={"Authorization": f"bearer {access_token}"},
        )
        self.log.debug("process status", process_status=process.json()["status"])
        return process.json()["status"]

    def _wait_for_completion(self, process_id: str) -> None:
        sleep(1)
        while self._check_process_status(process_id) == "running":
            self.log.info("waiting on workflow process to finish ...")
            sleep(3)
        self.log.info("workflow process finished")

    def activate(
        self, connection_id: UUID, src_port_id: str, src_vlan: int, dst_port_id: str, dst_vlan: int, bandwidth: int
    ) -> None:
        """Activate resources in NRM."""
        process = self._workflow_create(connection_id, src_port_id, src_vlan, dst_port_id, dst_vlan, bandwidth)
        self._wait_for_completion(process["id"])
        self._modify_note(connection_id, src_port_id, src_vlan, dst_port_id, dst_vlan, bandwidth)

    def deactivate(
        self, connection_id: UUID, src_port_id: str, src_vlan: int, dst_port_id: str, dst_vlan: int, bandwidth: int
    ) -> None:
        """Deactivate resources in NRM."""
        process = self._workflow_terminate(connection_id, src_port_id, src_vlan, dst_port_id, dst_vlan, bandwidth)
        self._wait_for_completion(process["id"])
