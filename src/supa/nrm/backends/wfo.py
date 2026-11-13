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
``wfo_product_id``, ``wfo_stp_tags`` and workflow names of your orchestrator there rather than
adding a second env file.
"""

import time
from json import dumps
from typing import Any, Callable, Dict, List, Optional, Tuple
from uuid import UUID

from pydantic import PositiveFloat
from pydantic_settings import BaseSettings, SettingsConfigDict
from requests import Response, get, post
from requests.auth import HTTPBasicAuth
from requests.exceptions import RequestException
from structlog.contextvars import bound_contextvars
from structlog.stdlib import BoundLogger

from supa import settings
from supa.connection.error import GenericRmError
from supa.job.shared import NsiException
from supa.nrm.backend import STP, BaseBackend
from supa.util.find import find_file

GRAPHQL_PAGE_SIZE = 100

POLL_INTERVAL = 3
"""Seconds between two polls of a process, and the first delay after a failed poll."""

MAX_POLL_BACKOFF = 30
"""Longest delay in seconds between two polls of a process that cannot be reached."""

NOTE_TIMEOUT = 30
"""Seconds to wait for the ``modify_note`` process; the circuit exists by then, so a slow note must not hold it back."""

TOKEN_EXPIRY_MARGIN = 60
"""Seconds before its expiry that a cached access token is replaced.

A token that lapses while a request is in flight is caught by the 401 retry, so this is not a hard bound.
"""

NO_ACCESS_TOKEN = ("", 0.0)
"""The empty cache: no token, due for replacement at once."""

GIVE_UP_STATUSES = frozenset({"failed", "aborted", "api_unavailable", "inconsistent_data", "suspended", "waiting"})
"""Process statuses in which SuPA stops waiting.

Besides the failures, ``suspended`` waits for form input that SuPA cannot supply, and ``waiting`` for a
step retry that only an operator or the periodic resume task of orchestrator-core (hourly by default)
starts. Any other status, known or not, is polled until ``completed`` or the deadline.
"""

STP_SUBSCRIPTIONS_QUERY = """
query StpSubscriptions($filterBy: [GraphqlFilter!], $first: Int!, $after: Int!) {
  subscriptions(filterBy: $filterBy, sortBy: [{field: "subscriptionId", order: ASC}], first: $first, after: $after) {
    page { subscriptionId }
    pageInfo { hasNextPage }
  }
}
"""

SUBSCRIPTION_STATUS_QUERY = """
query SubscriptionStatus($id: UUID!) {
  subscription(id: $id) { status }
}
"""


def _error_detail(response: Optional[Response]) -> Optional[str]:
    """Return the ``detail`` of an orchestrator error response, such as a form validation error."""
    if response is None:
        return None
    try:
        body = response.json()
    except ValueError:
        return None
    match body:
        case {"detail": detail}:
            return str(detail)
    return None


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
    stp_tags: str = "NSISTP"
    connect_timeout: float = 9.05
    read_timeout: float = 12.0
    write_timeout: float = 18.0
    process_timeout: PositiveFloat = 300.0


class Backend(BaseBackend):
    """Backend interface to a workflow orchestrator.

    Subclass this and override :meth:`_create_form` and :meth:`_stp_from_domain_model` to match
    the products and workflows of your own orchestrator; see the module docstring for an example.
    """

    # The cached token and the time.monotonic() at which to replace it; a tuple, so one assignment swaps both.
    _access_token: Tuple[str, float] = NO_ACCESS_TOKEN

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
        """Return the bearer token, or an empty string when OAuth2 is off.

        The token is cached until :data:`TOKEN_EXPIRY_MARGIN` seconds before it expires, so polls do not each
        fetch one. There is no lock: threads that find the cache empty together each fetch, the last one is kept.
        """
        access_token = ""  # noqa: S105
        if self.backend_settings.oauth2_active:
            access_token, replace_at = self._access_token
            if time.monotonic() >= replace_at:
                access_token, replace_at = self._fetch_access_token()
                self._access_token = (access_token, replace_at)
        self.log.debug(
            "workflow credentials", have_access_token=bool(access_token), base_url=self.backend_settings.base_url
        )
        return access_token

    def _fetch_access_token(self) -> Tuple[str, float]:
        """Ask the OIDC server for a token; return it with the ``time.monotonic()`` at which to replace it."""
        timeout = (self.backend_settings.connect_timeout, self.backend_settings.write_timeout)
        token_response = self._request_json(
            "unable to retrieve access token",
            self.backend_settings.oidc_url,
            lambda: post(
                self.backend_settings.oidc_url,
                auth=HTTPBasicAuth(self.backend_settings.oidc_user, self.backend_settings.oidc_password),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data="grant_type=client_credentials",
                timeout=timeout,
            ),
        )
        match token_response:
            case {"access_token": str() as access_token, "expires_in": int() | float() as lifetime} if access_token:
                pass
            case {"access_token": str() as access_token} if access_token:
                lifetime = 0  # without a usable expires_in the token is not cached
            case _:
                self.log.warning("token response without access_token", url=self.backend_settings.oidc_url)
                raise NsiException(GenericRmError, "token response without access_token")
        now = time.monotonic()
        replace_at = now + lifetime - TOKEN_EXPIRY_MARGIN
        # Info once per cached token; at debug for a token that is fetched again on every call.
        log = self.log.info if replace_at > now else self.log.debug
        log("retrieved access token", url=self.backend_settings.oidc_url, expires_in=token_response.get("expires_in"))
        return access_token, replace_at

    def _discard_access_token(self, token: str) -> None:
        """Forget ``token`` if it is still the cached one; another thread may have replaced it already."""
        if self._access_token[0] == token:
            self._access_token = NO_ACCESS_TOKEN

    def _send_authorised(self, method: Callable[..., Response], url: str, **kwargs: Any) -> Response:
        """Send a request with the bearer token; a 401 for a cached token is retried once with a new one.

        A 401 for a cached token means it was revoked, or its signing key rotated, before it expired. A token
        fetched for this request is not retried: a second one would be rejected as well.
        """
        cached = self._access_token[0]
        token = self._retrieve_access_token()
        response = method(url=url, headers={"Authorization": f"bearer {token}"}, **kwargs)
        if response.status_code == 401 and token and token == cached:
            self.log.warning("cached access token rejected, retrying with a new one", url=url)
            self._discard_access_token(token)
            retry_token = self._retrieve_access_token()
            response = method(url=url, headers={"Authorization": f"bearer {retry_token}"}, **kwargs)
        return response

    def _request_json(self, event: str, url: str, send: Callable[[], Response]) -> Any:
        """Send a request and return its JSON body.

        A transport error, non-2xx status or non-JSON body is logged as ``event`` and raised as
        ``NsiException``, with the orchestrator's error detail as reason when it has one.
        """
        start = time.time()
        try:
            response = send()
            response.raise_for_status()
            body = response.json()
        except RequestException as exc:
            reason = _error_detail(exc.response) or str(exc)
            self.log.warning(event, url=url, reason=reason)
            raise NsiException(GenericRmError, reason) from exc
        self.log.debug("request timer", url=url, seconds=time.time() - start)
        return body

    def _get_json(self, url: str) -> Any:
        """Get the JSON body of an authorised URL."""
        timeout = (self.backend_settings.connect_timeout, self.backend_settings.read_timeout)
        return self._request_json("cannot get url", url, lambda: self._send_authorised(get, url, timeout=timeout))

    def _post_json(self, url: str, json: Any) -> Any:
        """Post JSON to an authorised URL and return the JSON body of the response."""
        timeout = (self.backend_settings.connect_timeout, self.backend_settings.write_timeout)
        return self._request_json(
            "cannot post url", url, lambda: self._send_authorised(post, url, json=json, timeout=timeout)
        )

    def _start_process(self, workflow_name: str, json: Any) -> Any:
        """Start a workflow in the orchestrator and return the new process."""
        return self._post_json(
            f"{self.backend_settings.base_url}/api/processes/{workflow_name}?reporter={settings.nsa_host}", json
        )

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
        self.log.debug("create workflow payload", payload=dumps(json))
        return self._start_process(self.backend_settings.create_workflow_name, json)

    def _workflow_terminate(self, subscription_id: str) -> Any:
        self.log.info("start workflow terminate")
        json = [
            {"subscription_id": subscription_id},
            {},
        ]
        return self._start_process(self.backend_settings.terminate_workflow_name, json)

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
        self.log.debug("adding connection id to note of subscription")
        return self._start_process("modify_note", json)

    def _get_process_info(self, process_id: str) -> Any:
        """Get the process info; a body without ``last_status`` raises ``NsiException`` like a failed request."""
        url = f"{self.backend_settings.base_url}/api/processes/{process_id}"
        match self._get_json(url):
            case {"last_status": str() as status} as info:
                self.log.debug("process status", process_status=status)
                return info
            case _:
                self.log.warning("process info without last_status", url=url)
                raise NsiException(GenericRmError, "process info without last_status")

    @staticmethod
    def _process_ended(log: BoundLogger, info: Any) -> Any:
        """Return the info of a completed process; raise ``NsiException`` for any other ended process."""
        status = info["last_status"]
        if status == "completed":
            log.info("workflow finished", status=status)
            return info
        reason = info.get("failed_reason") or f"workflow process {status}"
        log.warning("workflow process did not complete", status=status, reason=reason)
        raise NsiException(GenericRmError, reason)

    def _wait_for_completion(self, process_id: str, timeout: Optional[float] = None) -> Any:
        """Poll the process until it ends and return its last process info.

        A failed poll is retried with backoff, since the process keeps running in the orchestrator whether or
        not SuPA can reach it. The last poll falls on the deadline, so the wait can overrun it by one poll.

        Args:
            process_id: The process to wait for.
            timeout: Seconds to wait, ``process_timeout`` when omitted.

        Raises:
            NsiException: The process failed or needs an operator, or the deadline passed first. In the latter
                case the process may still be running; the log line has its id.
        """
        log = self.log.bind(process_id=process_id)
        timeout = self.backend_settings.process_timeout if timeout is None else timeout
        deadline = time.monotonic() + timeout
        delay = backoff = POLL_INTERVAL
        time.sleep(1)
        while True:
            status: Optional[str] = None
            try:
                info = self._get_process_info(process_id)
            except NsiException:  # already logged by the request helper
                delay, backoff = backoff, min(2 * backoff, MAX_POLL_BACKOFF)
            else:
                status = info["last_status"]
                if status == "completed" or status in GIVE_UP_STATUSES:
                    return self._process_ended(log, info)
                log.debug("waiting on workflow to finish", status=status)
                delay = backoff = POLL_INTERVAL
            if (remaining := deadline - time.monotonic()) <= 0:
                state = f"still {status}" if status else "unreachable"
                reason = f"workflow process {state} after {timeout:g} s"
                log.warning("workflow process timed out", reason=reason)
                raise NsiException(GenericRmError, reason)
            time.sleep(min(delay, remaining))

    @staticmethod
    def _subscription_id_from(process_info: Any) -> str:
        state = process_info["current_state"]
        # Workflows either nest the subscription in the state or, like orchestrator-core's
        # store_process_subscription(), put the bare subscription_id there.
        subscription = state.get("subscription", state)
        return str(subscription["subscription_id"])

    def _graphql(self, query: str, variables: Dict[str, Any]) -> Any:
        """Run a query against the orchestrator GraphQL API and return its ``data``."""
        result = self._post_json(
            f"{self.backend_settings.base_url}/api/graphql", {"query": query, "variables": variables}
        )
        if errors := result.get("errors"):
            reason = "; ".join(error["message"] for error in errors)
            self.log.warning("graphql query failed", reason=reason)
            raise NsiException(GenericRmError, reason)
        return result["data"]

    def _get_nsi_stp_subscription_ids(self) -> List[str]:
        """Return the ids of the active subscriptions with one of the ``stp_tags`` product tags."""
        filter_by = [
            {"field": "tag", "value": self.backend_settings.stp_tags},
            {"field": "status", "value": "active"},
        ]
        subscription_ids: List[str] = []
        has_next_page = True
        while has_next_page:
            subscriptions = self._graphql(
                STP_SUBSCRIPTIONS_QUERY,
                {"filterBy": filter_by, "first": GRAPHQL_PAGE_SIZE, "after": len(subscription_ids)},
            )["subscriptions"]
            subscription_ids += [subscription["subscriptionId"] for subscription in subscriptions["page"]]
            has_next_page = subscriptions["pageInfo"]["hasNextPage"]
        return subscription_ids

    def _is_healthy(self, circuit_id: str) -> bool:
        subscription = self._graphql(SUBSCRIPTION_STATUS_QUERY, {"id": circuit_id})["subscription"]
        if subscription is None:
            raise NsiException(GenericRmError, "cannot find subscription in NRM")
        if subscription["status"].lower() == "terminated":  # definitely not active in NRM anymore
            self.log.warning("unhealthy")
            return False
        else:
            self.log.debug("healthy")
            return True

    def _get_domain_model(self, subscription_id: str) -> Any:
        """Fetch the domain model of a single subscription."""
        return self._get_json(f"{self.backend_settings.base_url}/api/subscriptions/domain-model/{subscription_id}")

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
            self._stp_from_domain_model(self._get_domain_model(subscription_id))
            for subscription_id in self._get_nsi_stp_subscription_ids()
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
        """Activate resources in NRM; the note on the subscription is best-effort, see the activate contract."""
        with bound_contextvars(primitive="activate", connection_id=str(connection_id)):
            process = self._workflow_create(src_port_id, src_vlan, dst_port_id, dst_vlan, bandwidth)
            subscription_id = self._subscription_id_from(self._wait_for_completion(process["id"]))
            with bound_contextvars(subscription_id=subscription_id):
                # The circuit exists now; failing on the note would leave it in the NRM unknown to SuPA.
                try:
                    self._wait_for_completion(self._add_note(connection_id, subscription_id)["id"], NOTE_TIMEOUT)
                except Exception as exc:
                    self.log.warning("failed to add note, circuit is active", reason=str(exc), exc_info=True)
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
        with bound_contextvars(primitive="deactivate", subscription_id=circuit_id, connection_id=str(connection_id)):
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
        with bound_contextvars(primitive="health_check", subscription_id=circuit_id, connection_id=str(connection_id)):
            return self._is_healthy(circuit_id)

    def topology(self) -> List[STP]:
        """Get exposed topology from NRM."""
        with bound_contextvars(primitive="topology"):
            return self._get_topology()
