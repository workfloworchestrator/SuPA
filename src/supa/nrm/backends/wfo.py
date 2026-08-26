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
"""Backend for a Workflow Orchestrator (orchestrator-core).

The transport, OAuth2, process polling and subscription lookups are generic: they only use
endpoints that orchestrator-core ships.  Two methods carry the shape of *your* orchestrator's
product and workflows; override them in a module on ``PYTHONPATH`` and set ``backend=my_wfo``::

    # my_wfo.py
    from typing import Any, Dict, List

    from supa.nrm.backend import STP
    from supa.nrm.backends.wfo import Backend as WfoBackend

    class Backend(WfoBackend):
        def _create_form(
            self, src_port_id: str, src_vlan: int, dst_port_id: str, dst_vlan: int, bandwidth: int
        ) -> List[Dict[str, Any]]:
            # One dict per form page the create workflow yields.
            return [
                {"product": self.backend_settings.product_id},
                {
                    "circuit_description": "SuPA connection",
                    "source_stp": src_port_id,
                    "source_vlan": src_vlan,
                    "destination_stp": dst_port_id,
                    "destination_vlan": dst_vlan,
                    "service_speed": bandwidth,
                },
                {},  # summary form
            ]

        def _stp_from_domain_model(self, domain_model: Dict[str, Any]) -> STP:
            stp = domain_model["stp"]
            return STP(
                stp_id=stp["stp_id"],
                port_id=domain_model["subscription_id"],
                vlans=stp["label_group"],
                description=stp["stp_name"],
                bandwidth=stp["capacity"],
            )

A subclass still reads ``wfo.env``, because it inherits ``__init__``.  Put the ``wfo_base_url``,
``wfo_product_id``, ``wfo_stp_query`` and workflow names of your orchestrator there rather than
adding a second env file.
"""

import time
from json import dumps, loads
from time import sleep
from typing import Any, Dict, List, Optional
from urllib.parse import quote
from uuid import UUID

from pydantic_settings import BaseSettings, SettingsConfigDict
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

    See also: the ``src/supa/nrm/backends/wfo.env`` file
    """

    model_config = SettingsConfigDict(env_prefix="wfo_")

    base_url: str = "http://localhost"
    oauth2_active: bool = False
    oidc_url: str = ""
    oidc_user: str = ""
    oidc_password: str = ""
    create_workflow_name: str = ""
    terminate_workflow_name: str = ""
    customer_id: str = ""
    product_id: str = ""
    stp_query: str = "tag:NSISTP status:active"
    connect_timeout: float = 9.05
    read_timeout: float = 12.0
    write_timeout: float = 18.0


class Backend(BaseBackend):
    """Backend interface to a workflow orchestrator.

    Subclass this and override :meth:`_create_form` and :meth:`_stp_from_domain_model` to match
    the products and workflows of your own orchestrator; see the module docstring for an example.
    """

    def __init__(self) -> None:
        """Load properties from 'wfo.env'."""
        super(Backend, self).__init__()
        try:
            # first look for wfo.env directly on the sys path
            env_file = find_file("wfo.env")
        except FileNotFoundError:
            try:
                # else look for wfo.env in an installed supa package
                env_file = find_file("supa/nrm/backends/wfo.env")
            except FileNotFoundError:
                env_file = None
        if env_file:
            self.backend_settings = BackendSettings(_env_file=env_file)  # type: ignore[call-arg]
            self.log.info("Read backend properties", path=str(env_file))
        else:
            raise FileNotFoundError("Backend wfo env file not found")

    def _retrieve_access_token(self) -> str:
        access_token = ""  # noqa: S105
        timeout = (self.backend_settings.connect_timeout, self.backend_settings.write_timeout)
        if self.backend_settings.oauth2_active:
            self.log.debug("retrieve access token")
            start = time.time()
            try:
                token = post(
                    self.backend_settings.oidc_url,
                    auth=HTTPBasicAuth(self.backend_settings.oidc_user, self.backend_settings.oidc_password),
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    data="grant_type=client_credentials",
                    timeout=timeout,
                )
            except RequestException as requests_exception:
                self.log.warning("unable to retrieve access token", reason=str(requests_exception))
                raise NsiException(GenericRmError, str(requests_exception)) from requests_exception
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
        self.log.debug(
            "workflow credentials", have_access_token=bool(access_token), base_url=self.backend_settings.base_url
        )
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

    def _create_form(
        self, src_port_id: str, src_vlan: int, dst_port_id: str, dst_vlan: int, bandwidth: int
    ) -> List[Dict[str, Any]]:
        """Build the input form for the create workflow, one dict per form page.

        This is the shape of a specific orchestrator product; override it to match yours.
        """
        return [
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

    def _workflow_create(self, src_port_id: str, src_vlan: int, dst_port_id: str, dst_vlan: int, bandwidth: int) -> Any:
        self.log.info("start workflow create")
        json = self._create_form(src_port_id, src_vlan, dst_port_id, dst_vlan, bandwidth)
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

    def _get_global_reservation_id(self, connection_id: UUID) -> str:
        """Look up the global reservation id, which is not among the backend method arguments."""
        from supa.db.model import Reservation
        from supa.db.session import db_session

        with db_session() as session:
            global_reservation_id = (
                session.query(Reservation.global_reservation_id)
                .filter(Reservation.connection_id == connection_id)
                .scalar()
            )
        return str(global_reservation_id)

    def _add_note(self, connection_id: UUID, subscription_id: str) -> Any:
        self.log.info("start workflow modify note")
        global_reservation_id = self._get_global_reservation_id(connection_id)
        json = [
            {
                "subscription_id": subscription_id,
            },
            {
                "note": (
                    f"NSI  - host {settings.nsa_host} - NSA ID {settings.nsa_id}"
                    f" - connection ID {connection_id} - global reservation ID {global_reservation_id}"
                )
            },
        ]
        base_url = self.backend_settings.base_url
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
        state = process.json()["current_state"]
        # Workflows either nest the subscription in the state or, like orchestrator-core's
        # store_process_subscription(), put the bare subscription_id there.
        subscription = state.get("subscription", state)
        return str(subscription["subscription_id"])

    def _get_nsi_stp_subscriptions(self) -> Any:
        nsi_stp_subscriptions = self._get_url(
            f"{self.backend_settings.base_url}/api/subscriptions/search?query={quote(self.backend_settings.stp_query)}"
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

    def _get_domain_model(self, subscription_id: str) -> Any:
        """Fetch the domain model of a single subscription."""
        domain_model = self._get_url(
            f"{self.backend_settings.base_url}/api/subscriptions/domain-model/{subscription_id}"
        )
        if domain_model.status_code != 200:
            try:
                domain_model.raise_for_status()
            except HTTPError as http_err:
                self.log.warning(
                    "failed to fetch STP domain model",
                    reason=str(http_err),
                    nsi_stp_subscription_id=subscription_id,
                )
                raise NsiException(GenericRmError, str(http_err)) from http_err
        return domain_model.json()

    def _stp_from_domain_model(self, domain_model: Dict[str, Any]) -> STP:
        """Map a subscription domain model onto an :class:`~supa.nrm.backend.STP`.

        This reads the fields of a specific orchestrator product; override it to match yours.
        """
        stp_settings = domain_model["settings"]
        return STP(
            topology=stp_settings["topology"],
            stp_id=stp_settings["stp_id"],
            port_id=stp_settings["sap"]["port"]["owner_subscription_id"],
            vlans=stp_settings["sap"]["vlanrange"],
            description=stp_settings["stp_description"],
            is_alias_in=stp_settings["is_alias_in"],
            is_alias_out=stp_settings["is_alias_out"],
            bandwidth=stp_settings["bandwidth"],
            enabled=stp_settings["expose_in_topology"],
        )

    def _get_topology(self) -> List[STP]:
        self.log.debug("get topology from NRM")
        return [
            self._stp_from_domain_model(self._get_domain_model(nsi_stp_sub["subscription_id"]))
            for nsi_stp_sub in self._get_nsi_stp_subscriptions()
        ]

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
    ) -> Optional[str]:
        """Deactivate resources in NRM.

        The subscription is terminated, so there is no circuit_id left to return.
        """
        self.log = self.log.bind(primitive="deactivate", subscription_id=circuit_id, connection_id=str(connection_id))
        process = self._workflow_terminate(circuit_id)
        self._wait_for_completion(process["id"])
        return None

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
