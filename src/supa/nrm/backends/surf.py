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
import time
from json import dumps, loads
from time import sleep
from typing import Any, List
from uuid import UUID

from pydantic_settings import BaseSettings
from requests import Response, get, post
from requests.auth import HTTPBasicAuth
from requests.exceptions import ConnectionError, HTTPError, RequestException  # noqa: A004
from structlog.stdlib import BoundLogger

from supa import settings
from supa.connection.error import GenericRmError
from supa.job.shared import NsiException
from supa.nrm.backend import STP, BaseBackend
from supa.util.find import find_file


class BackendSettings(BaseSettings):
    """Backend settings with default values.

    See also: the ``src/supa/nrm/backends/surf.env`` file
    """

    base_url: str = "http://localhost"
    oauth2_active: bool = False
    oidc_url: str = ""
    oidc_user: str = ""
    oidc_password: str = ""
    create_workflow_name: str = ""
    terminate_workflow_name: str = ""
    customer_id: str = ""
    product_id: str = ""
    connect_timeout: float = 9.05
    read_timeout: float = 12.0
    write_timeout: float = 18.0


class Backend(BaseBackend):
    """SURF backend interface to workflow orchestrator."""

    def __init__(self) -> None:
        """Load properties from 'surf.env'."""
        super(Backend, self).__init__()
        self.backend_settings = BackendSettings(_env_file=(env_file := find_file("surf.env")))  # type: ignore[call-arg]
        self.log.info("Read backend properties", path=str(env_file))

    def _retrieve_access_token(self) -> str:
        access_token = ""  # noqa: S105
        timeout = (self.backend_settings.connect_timeout, self.backend_settings.write_timeout)
        if self.backend_settings.oauth2_active:
            self.log.debug("retrieve access token")
            start = time.time()
            token = post(
                self.backend_settings.oidc_url,
                auth=HTTPBasicAuth(self.backend_settings.oidc_user, self.backend_settings.oidc_password),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data="grant_type=client_credentials",
                timeout=timeout,
            )
            self.log.debug("retrieve access token timer", seconds=time.time() - start)
            if token:
                if token.status_code > 210:
                    try:
                        token.raise_for_status()
                    except HTTPError as http_err:
                        self.log.warning("unable to authenticate", reason=str(http_err))
                        raise NsiException(GenericRmError, str(http_err)) from http_err
                else:
                    access_token = token.json()["access_token"]
        self.log.debug("workflow credentials", access_token=access_token, base_url=self.backend_settings.base_url)
        return access_token

    def _get_url(self, url: str) -> Response:
        """Get response from authorised URL."""
        access_token = self._retrieve_access_token()
        headers = {"Authorization": f"bearer {access_token}"}
        timeout = (self.backend_settings.connect_timeout, self.backend_settings.read_timeout)
        start = time.time()
        try:
            response = get(url=url, headers=headers, timeout=timeout)
        except RequestException as requests_exception:
            self.log.warning("cannot get url", reason=str(requests_exception))
            raise NsiException(GenericRmError, str(requests_exception)) from requests_exception
        self.log.debug("get url timer", url=url, seconds=time.time() - start)
        return response

    def _post_url_json(self, url: str, json: Any) -> Response:
        """Post JSON request to authorised URL."""
        access_token = self._retrieve_access_token()
        headers = {"Authorization": f"bearer {access_token}", "Content-Type": "application/json"}
        timeout = (self.backend_settings.connect_timeout, self.backend_settings.write_timeout)
        start = time.time()
        response = post(url=url, headers=headers, json=json, timeout=timeout)
        self.log.debug("post url timer", url=url, seconds=time.time() - start)
        return response

    def _workflow_create(self, src_port_id: str, src_vlan: int, dst_port_id: str, dst_vlan: int, bandwidth: int) -> Any:
        self.log.info("start workflow create")
        json = [
            {
                "product": self.backend_settings.product_id,
            },
            {
                "customer_id": self.backend_settings.customer_id,
                "service_ports": [
                    {
                        "subscription_id": src_port_id,
                        "vlan": str(src_vlan),
                    },
                    {
                        "subscription_id": dst_port_id,
                        "vlan": str(dst_vlan),
                    },
                ],
                "service_speed": str(bandwidth),
                "speed_policer": True,
            },
            {},  # summary form
        ]
        base_url = self.backend_settings.base_url
        create_workflow_name = self.backend_settings.create_workflow_name
        reporter = settings.nsa_host
        self.log.debug("create workflow payload", payload=dumps(json))
        try:
            result = self._post_url_json(
                url=f"{base_url}/api/processes/{create_workflow_name}?reporter={reporter}", json=json
            )
        except ConnectionError as con_err:
            self.log.warning("call to orchestrator failed", reason=str(con_err))
            raise NsiException(GenericRmError, str(con_err)) from con_err
        if result.status_code > 210:
            try:
                result.raise_for_status()
            except HTTPError as http_err:
                if http_err.response.status_code == 400:
                    self.log.warning("workflow failed", reason=loads(http_err.response.content)["detail"])
                    raise NsiException(GenericRmError, loads(http_err.response.content)["detail"]) from http_err
                else:
                    self.log.warning("workflow failed", reason=str(http_err))
                    raise NsiException(GenericRmError, str(http_err)) from http_err
        return result.json()

    def _workflow_terminate(self, subscription_id: str) -> Any:
        self.log.info("start workflow terminate")
        json = [
            {"subscription_id": subscription_id},
            {},
        ]
        base_url = self.backend_settings.base_url
        terminate_workflow_name = self.backend_settings.terminate_workflow_name
        reporter = settings.nsa_host
        try:
            result = self._post_url_json(
                url=f"{base_url}/api/processes/{terminate_workflow_name}?reporter={reporter}", json=json
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

    def _add_note(self, connection_id: UUID, subscription_id: str) -> Any:
        self.log.info("start workflow modify note")
        base_url = self.backend_settings.base_url
        json = [
            {
                "subscription_id": subscription_id,
            },
            {
                "note": (
                    "NSI "
                    f" - host {settings.nsa_host}"
                    f" - NSA ID {settings.nsa_id}"
                    f" - connection ID {connection_id}"
                )
            },
        ]
        reporter = settings.nsa_host
        try:
            self.log.debug("adding connection id to note of subscription")
            result = self._post_url_json(url=f"{base_url}/api/processes/modify_note?reporter={reporter}", json=json)
        except ConnectionError as con_err:
            self.log.warning("call to orchestrator failed", reason=str(con_err))
            raise NsiException(GenericRmError, str(con_err)) from con_err
        if result.status_code > 210:
            try:
                result.raise_for_status()
            except HTTPError as http_err:
                self.log.warning("failed to add note to subscription", reason=str(http_err))
                raise NsiException(GenericRmError, str(http_err)) from http_err
        return result.json()

    def _get_process_info(self, process_id: str) -> Any:
        process = self._get_url(f"{self.backend_settings.base_url}/api/processes/{process_id}")
        self.log.debug("process status", process_status=process.json()["last_status"])
        return process.json()

    def _wait_for_completion(self, process_id: str) -> None:
        log = self.log.bind(process_id=process_id)
        sleep(1)
        while (info := self._get_process_info(process_id))["last_status"] == "created" or info[
            "last_status"
        ] == "running":
            log.debug("waiting on workflow to finish", status=info["last_status"])
            sleep(3)
        if info["last_status"] == "completed":
            log.info("workflow finished", status=info["last_status"])
        else:
            log.warning("workflow process failed", status=info["last_status"], reason=info["failed_reason"])
            raise NsiException(GenericRmError, info["failed_reason"]) from None

    def _get_subscription_id(self, process_id: str) -> str:
        process = self._get_url(f"{self.backend_settings.base_url}/api/processes/{process_id}")
        self.log.debug("process status", process_status=process.json()["last_status"])
        return str(process.json()["current_state"]["subscription"]["subscription_id"])

    def _get_nsi_stp_subscriptions(self) -> Any:
        nsi_stp_subscriptions = self._get_url(
            f"{self.backend_settings.base_url}/api/pythia_legacy/subscriptions/?filter=status,active,tag,NSISTP-NSISTPNL"  # noqa: E501
        )
        if nsi_stp_subscriptions.status_code != 200:
            try:
                nsi_stp_subscriptions.raise_for_status()
            except HTTPError as http_err:
                self.log.warning("failed to fetch NSISTP subscriptions", reason=str(http_err))
                raise NsiException(GenericRmError, str(http_err)) from http_err
        return nsi_stp_subscriptions.json()

    def _is_healthy(self, circuit_id: str) -> bool:
        subscription_search = self._get_url(
            f"{self.backend_settings.base_url}/api/subscriptions/search?query=subscription_id:{circuit_id}"
        )
        if subscription_search.status_code != 200:
            try:
                subscription_search.raise_for_status()
            except HTTPError as http_err:
                raise NsiException(GenericRmError, str(http_err)) from http_err
        subscriptions = subscription_search.json()
        if len(subscriptions) != 1:
            raise NsiException(GenericRmError, "cannot find subscription in NRM")
        if subscriptions[0]["subscription_id"] != circuit_id:  # cannot happen, but we are paranoid
            raise NsiException(GenericRmError, "subscription_id does not match circuit_id")
        if subscriptions[0]["status"] == "terminated":  # definitely not active in NRM anymore
            self.log.warning("unhealthy")
            return False
        else:
            self.log.debug("healthy")
            return True

    def _get_topology(self) -> List[STP]:
        self.log.debug("get topology from NRM")
        ports: List[STP] = []
        for nsi_stp_sub in self._get_nsi_stp_subscriptions():
            nsi_stp_dm = self._get_url(
                f"{self.backend_settings.base_url}/api/subscriptions/domain-model/{nsi_stp_sub['subscription_id']}"
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
                        port_id=nsi_stp_dict["settings"]["sap"]["port"]["owner_subscription_id"],
                        vlans=nsi_stp_dict["settings"]["sap"]["vlanrange"],
                        description=nsi_stp_dict["settings"]["stp_description"],
                        is_alias_in=nsi_stp_dict["settings"]["is_alias_in"],
                        is_alias_out=nsi_stp_dict["settings"]["is_alias_out"],
                        bandwidth=nsi_stp_dict["settings"]["bandwidth"],
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
        process = self._workflow_create(src_port_id, src_vlan, dst_port_id, dst_vlan, bandwidth)
        self._wait_for_completion(process["id"])
        subscription_id = self._get_subscription_id(process["id"])
        self.log = self.log.bind(subscription_id=subscription_id)
        process = self._add_note(connection_id, subscription_id)
        self._wait_for_completion(process["id"])
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

    def health_check(
        self,
        connection_id: UUID,
        bandwidth: int,
        src_port_id: str,
        src_vlan: int,
        dst_port_id: str,
        dst_vlan: int,
        circuit_id: str,
    ) -> bool:
        """Check if the connection/circuit is healthy in NRM."""
        self.log = self.log.bind(primitve="health_check", subscription_id=circuit_id, connection_id=str(connection_id))
        return self._is_healthy(circuit_id)

    def topology(self) -> List[STP]:
        """Get exposed topology from NRM."""
        self.log = self.log.bind(primitive="topology")
        return self._get_topology()
