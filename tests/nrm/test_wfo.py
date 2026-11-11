"""Unit tests for the WFO NRM backend topology/auth path.

These tests cover the outbound HTTP helpers that the topology refresh depends on
(``_retrieve_access_token``, ``_get_json``, ``_get_nsi_stp_subscription_ids``, ``_is_healthy`` and
``_get_topology``).  All network access is mocked at the module-level ``requests``
``post``/``get`` functions so no real HTTP traffic is made.
"""

from typing import Any, Dict, List, Optional, Type
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest
import structlog
from requests.exceptions import HTTPError, JSONDecodeError, ReadTimeout

from supa.job.shared import NsiException
from supa.nrm.backend import STP
from supa.nrm.backends.wfo import Backend, BackendSettings


class ExampleBackend(Backend):
    """The subclass from the ``supa.nrm.backends.wfo`` module docstring.

    Kept here verbatim so the published example is exercised by CI and cannot rot.  It maps onto
    an orchestrator whose product uses ``source_stp``/``service_speed`` on the create form and
    ``stp_name``/``capacity``/``label_group`` on the STP block.
    """

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


def make_backend(backend_class: Type[Backend] = Backend, **overrides: Any) -> Backend:
    """Build a ``Backend`` without depending on ``wfo.env`` discovery."""
    settings = {
        "base_url": "http://nrm.test",
        "oauth2_active": True,
        "oidc_url": "http://oidc.test/token",
        "oidc_user": "user",
        "oidc_password": "password",  # noqa: S106
        **overrides,
    }
    backend = object.__new__(backend_class)
    backend.log = structlog.get_logger()
    backend.backend_settings = BackendSettings(**settings)
    return backend


def make_response(status_code: int = 200, json_data: Optional[Any] = None) -> MagicMock:
    """Build a mock ``requests.Response`` whose ``raise_for_status`` raises on 4xx/5xx, like the real one."""
    response = MagicMock(name=f"Response[{status_code}]")
    response.status_code = status_code
    response.json.return_value = {} if json_data is None else json_data
    if status_code >= 400:
        response.raise_for_status.side_effect = HTTPError(f"{status_code} Error", response=response)
    else:
        response.raise_for_status.return_value = None
    return response


def make_non_json_response(status_code: int) -> MagicMock:
    """Build a mock response whose body is not JSON, such as an HTML page from a proxy."""
    response = make_response(status_code)
    response.json.side_effect = JSONDecodeError("not JSON", "<html>", 0)
    return response


@pytest.mark.parametrize(
    ("oauth2_active", "expected_token"),
    [
        pytest.param(False, "", id="oauth2-inactive-returns-empty"),
        pytest.param(True, "the-token", id="success-returns-token"),
    ],
)
def test_retrieve_access_token_returns_token(oauth2_active: bool, expected_token: str) -> None:
    """``_retrieve_access_token`` returns the bearer token, or an empty string when OAuth2 is off."""
    backend = make_backend(oauth2_active=oauth2_active)
    with patch(
        "supa.nrm.backends.wfo.post", return_value=make_response(200, {"access_token": "the-token"})
    ) as mock_post:
        assert backend._retrieve_access_token() == expected_token
        if oauth2_active:
            mock_post.assert_called_once()
        else:
            mock_post.assert_not_called()


@pytest.mark.parametrize(
    "post_mock",
    [
        # A raw ReadTimeout would escape and be rendered as a CherryPy traceback.
        pytest.param({"side_effect": ReadTimeout("read timed out")}, id="timeout"),
        # An empty token would only surface later as a 401 from the orchestrator.
        pytest.param({"return_value": make_response(401)}, id="unauthorized"),
    ],
)
def test_retrieve_access_token_failure_raises_nsi_exception(post_mock: Dict[str, Any]) -> None:
    """A token-endpoint failure raises ``NsiException``."""
    backend = make_backend()
    with patch("supa.nrm.backends.wfo.post", **post_mock):
        with pytest.raises(NsiException):
            backend._retrieve_access_token()


def test_get_json_success_returns_body() -> None:
    """``_get_json`` returns the JSON body of an authorised GET."""
    backend = make_backend(oauth2_active=False)
    with patch("supa.nrm.backends.wfo.get", return_value=make_response(200, {"ok": True})) as mock_get:
        assert backend._get_json("http://nrm.test/api/thing") == {"ok": True}
        mock_get.assert_called_once()


def test_get_json_request_exception_raises_nsi_exception() -> None:
    """``_get_json`` converts a ``requests`` transport error into an ``NsiException``."""
    backend = make_backend(oauth2_active=False)
    with patch("supa.nrm.backends.wfo.get", side_effect=ReadTimeout("boom")):
        with pytest.raises(NsiException):
            backend._get_json("http://nrm.test/api/thing")


@pytest.mark.parametrize(
    ("post_mock", "reason"),
    [
        pytest.param(
            {"return_value": make_response(400, {"detail": "Vlan(s) 2389 not valid nsi vlan range"})},
            "Vlan(s) 2389 not valid nsi vlan range",
            id="orchestrator-detail",
        ),
        pytest.param({"return_value": make_response(500, ["no detail"])}, "500 Error", id="body-without-detail"),
        pytest.param({"return_value": make_non_json_response(502)}, "502 Error", id="non-json-error-body"),
        pytest.param(
            {"return_value": make_non_json_response(200)}, "not JSON: line 1 column 1 (char 0)", id="non-json-2xx-body"
        ),
        pytest.param({"side_effect": ReadTimeout("read timed out")}, "read timed out", id="transport-error"),
    ],
)
def test_post_json_failure_raises_nsi_exception_with_reason(post_mock: Dict[str, Any], reason: str) -> None:
    """``_post_json`` raises ``NsiException``, with the orchestrator's ``detail`` as reason when it has one."""
    backend = make_backend(oauth2_active=False)
    with patch("supa.nrm.backends.wfo.post", **post_mock):
        with pytest.raises(NsiException) as exc_info:
            backend._post_json("http://nrm.test/api/processes/create", [])
    assert exc_info.value.extra_info == reason


def subscriptions_page(subscription_ids: List[str], has_next_page: bool = False) -> MagicMock:
    """Build a GraphQL ``subscriptions`` response holding one page of subscription ids."""
    return make_response(
        200,
        {
            "data": {
                "subscriptions": {
                    "page": [{"subscriptionId": subscription_id} for subscription_id in subscription_ids],
                    "pageInfo": {"hasNextPage": has_next_page},
                }
            }
        },
    )


def test_get_nsi_stp_subscription_ids_filters_on_configured_tags() -> None:
    """``_get_nsi_stp_subscription_ids`` queries GraphQL for active subscriptions with ``stp_tags``."""
    backend = make_backend(oauth2_active=False, stp_tags="MYSTP|MYSTPNL")
    with patch("supa.nrm.backends.wfo.post", return_value=subscriptions_page(["sub-1"])) as mock_post:
        assert backend._get_nsi_stp_subscription_ids() == ["sub-1"]
    assert mock_post.call_args.kwargs["url"] == "http://nrm.test/api/graphql"
    assert mock_post.call_args.kwargs["json"]["variables"]["filterBy"] == [
        {"field": "tag", "value": "MYSTP|MYSTPNL"},
        {"field": "status", "value": "active"},
    ]


def test_get_nsi_stp_subscription_ids_follows_pages() -> None:
    """``_get_nsi_stp_subscription_ids`` keeps fetching while ``hasNextPage``, offset by what it has."""
    backend = make_backend(oauth2_active=False)
    pages = [subscriptions_page(["sub-1", "sub-2"], has_next_page=True), subscriptions_page(["sub-3"])]
    with patch("supa.nrm.backends.wfo.post", side_effect=pages) as mock_post:
        assert backend._get_nsi_stp_subscription_ids() == ["sub-1", "sub-2", "sub-3"]
    assert [call.kwargs["json"]["variables"]["after"] for call in mock_post.call_args_list] == [0, 2]


@pytest.mark.parametrize(
    "post_mock",
    [
        pytest.param({"side_effect": ReadTimeout("boom")}, id="transport-error"),
        pytest.param({"return_value": make_response(500)}, id="http-error"),
        pytest.param(
            {"return_value": make_response(200, {"data": None, "errors": [{"message": "Invalid filter arguments"}]})},
            id="graphql-error",
        ),
    ],
)
def test_graphql_failure_raises_nsi_exception(post_mock: Dict[str, Any]) -> None:
    """``_graphql`` raises ``NsiException`` on a transport error, an HTTP error or a GraphQL ``errors`` entry."""
    backend = make_backend(oauth2_active=False)
    with patch("supa.nrm.backends.wfo.post", **post_mock):
        with pytest.raises(NsiException):
            backend._graphql("query { version }", {})


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        pytest.param("ACTIVE", True, id="active"),
        pytest.param("PROVISIONING", True, id="provisioning"),
        pytest.param("TERMINATED", False, id="terminated"),
    ],
)
def test_is_healthy_reflects_subscription_status(status: str, expected: bool) -> None:
    """``_is_healthy`` is ``False`` only for a terminated subscription."""
    backend = make_backend(oauth2_active=False)
    response = make_response(200, {"data": {"subscription": {"status": status}}})
    with patch("supa.nrm.backends.wfo.post", return_value=response) as mock_post:
        assert backend._is_healthy("sub-1") is expected
    assert mock_post.call_args.kwargs["json"]["variables"] == {"id": "sub-1"}


def test_is_healthy_unknown_subscription_raises_nsi_exception() -> None:
    """``_is_healthy`` raises ``NsiException`` when the orchestrator does not know the subscription."""
    backend = make_backend(oauth2_active=False)
    with patch("supa.nrm.backends.wfo.post", return_value=make_response(200, {"data": {"subscription": None}})):
        with pytest.raises(NsiException):
            backend._is_healthy("sub-1")


DOMAIN_MODEL = {
    "settings": {
        "topology": "topology",
        "stp_id": "stp-1",
        "sap": {"port": {"owner_subscription_id": "port-1"}, "vlanrange": "100-200"},
        "stp_description": "Test STP",
        "is_alias_in": None,
        "is_alias_out": None,
        "bandwidth": 1000,
        "expose_in_topology": True,
    }
}

EXAMPLE_DOMAIN_MODEL = {
    "subscription_id": "port-1",
    "stp": {"stp_id": "stp-1", "stp_name": "Test STP", "label_group": "100-200", "capacity": 1000},
}


@pytest.mark.parametrize(
    ("backend_class", "domain_model"),
    [
        pytest.param(Backend, DOMAIN_MODEL, id="default-nsistp-product"),
        pytest.param(ExampleBackend, EXAMPLE_DOMAIN_MODEL, id="subclass-overriding-the-mapping"),
    ],
)
def test_get_topology_builds_stp_list(backend_class: Type[Backend], domain_model: Dict[str, Any]) -> None:
    """``_get_topology`` maps a subscription's domain model onto an ``STP``.

    Both the built-in product shape and a subclass that overrides ``_stp_from_domain_model``
    must produce the same ``STP``.
    """
    backend = make_backend(backend_class, oauth2_active=False)
    with (
        patch.object(backend, "_get_nsi_stp_subscription_ids", return_value=["sub-1"]),
        patch.object(backend, "_get_json", return_value=domain_model),
    ):
        stps = backend._get_topology()
    assert len(stps) == 1
    stp = stps[0]
    assert stp.stp_id == "stp-1"
    assert stp.port_id == "port-1"
    assert stp.vlans == "100-200"
    assert stp.description == "Test STP"
    assert stp.bandwidth == 1000
    assert stp.enabled is True


def test_add_note_ends_with_global_reservation_id(connection_id: UUID) -> None:
    """The note posted to the orchestrator ends with the global reservation id of the connection.

    ``global_reservation_id`` lives on ``Reservation``, not on ``Connection``, so it is not among
    the arguments the backend is called with and has to be looked up in the database.
    """
    backend = make_backend(oauth2_active=False)
    with patch("supa.nrm.backends.wfo.post", return_value=make_response(200, {"id": "process-1"})) as mock_post:
        backend._add_note(connection_id, "sub-1")
    assert mock_post.call_args.kwargs["json"][1]["note"].endswith(
        f" - connection ID {connection_id} - global reservation ID global reservation id"
    )


def test_create_form_override_is_used_by_workflow_create() -> None:
    """``_workflow_create`` posts whatever ``_create_form`` returns, so a subclass can reshape it."""
    backend = make_backend(ExampleBackend, oauth2_active=False, create_workflow_name="create_thing")
    with patch("supa.nrm.backends.wfo.post", return_value=make_response(200, {"id": "process-1"})) as mock_post:
        backend._workflow_create("port-1", 100, "port-2", 200, 1000)
    assert mock_post.call_args.kwargs["url"].startswith("http://nrm.test/api/processes/create_thing?reporter=")
    assert mock_post.call_args.kwargs["json"][1] == {
        "circuit_description": "SuPA connection",
        "source_stp": "port-1",
        "source_vlan": 100,
        "destination_stp": "port-2",
        "destination_vlan": 200,
        "service_speed": 1000,
    }


def test_get_topology_domain_model_non_200_raises_nsi_exception() -> None:
    """``_get_topology`` raises ``NsiException`` when a domain-model fetch fails."""
    backend = make_backend(oauth2_active=False)
    with (
        patch.object(backend, "_get_nsi_stp_subscription_ids", return_value=["sub-1"]),
        patch("supa.nrm.backends.wfo.get", return_value=make_response(404)),
    ):
        with pytest.raises(NsiException):
            backend._get_topology()


def test_topology_delegates_to_get_topology() -> None:
    """The public ``topology()`` returns the list produced by ``_get_topology``."""
    backend = make_backend(oauth2_active=False)
    sentinel = [STP(stp_id="stp-1", port_id="port-1", vlans="100-200")]
    with patch.object(backend, "_get_topology", return_value=sentinel):
        assert backend.topology() == sentinel


def test_topology_token_timeout_raises_nsi_exception() -> None:
    """End-to-end: a token timeout during ``topology()`` surfaces as ``NsiException``.

    This is the realistic failure that reaches the healthcheck endpoint; surfacing it as an
    ``NsiException`` (rather than a raw ``ReadTimeout``) is what lets ``_check_topology()``
    return an HTTP 503 instead of leaking a CherryPy stack trace.  Red before the ``wfo.py``
    fix, green after.
    """
    backend = make_backend(oauth2_active=True)
    with patch("supa.nrm.backends.wfo.post", side_effect=ReadTimeout("read timed out")):
        with pytest.raises(NsiException):
            backend.topology()


def test_primitive_context_does_not_leak_into_later_calls() -> None:
    """Each primitive logs with its own context only, and leaves none behind on the shared backend."""
    backend = make_backend(oauth2_active=False)
    with (
        structlog.testing.capture_logs(processors=[structlog.contextvars.merge_contextvars]) as logs,
        patch.object(backend, "_get_topology", side_effect=lambda: backend.log.info("in topology") or []),
        patch.object(backend, "_is_healthy", side_effect=lambda circuit_id: backend.log.info("in health") or True),
    ):
        backend.health_check(UUID(int=1), 1000, "src", 1, "dst", 2, "sub-1")
        backend.topology()
        backend.log.info("after")

    assert [{k: v for k, v in log.items() if k != "log_level"} for log in logs] == [
        {
            "event": "in health",
            "primitive": "health_check",
            "subscription_id": "sub-1",
            "connection_id": str(UUID(int=1)),
        },
        {"event": "in topology", "primitive": "topology"},
        {"event": "after"},
    ]


@pytest.mark.parametrize("status_code", [401, 500])
def test_wait_for_completion_non_2xx_raises_nsi_exception(status_code: int) -> None:
    """A process poll that is refused raises ``NsiException``, not a ``KeyError`` on ``last_status``."""
    backend = make_backend(oauth2_active=False)
    with (
        patch("supa.nrm.backends.wfo.sleep"),
        patch("supa.nrm.backends.wfo.get", return_value=make_response(status_code, {"detail": "Unauthorized"})),
    ):
        with pytest.raises(NsiException):
            backend._wait_for_completion("process-1")


NOTE_STARTED = make_response(200, {"id": "note"})


@pytest.mark.parametrize(
    ("note_post", "note_response"),
    [
        pytest.param(NOTE_STARTED, make_response(200, {"last_status": "completed"}), id="note-completed"),
        pytest.param(ReadTimeout("timed out"), None, id="note-post-times-out"),
        pytest.param(make_response(401), None, id="note-post-unauthorized"),
        pytest.param(make_response(200, {}), None, id="note-response-without-id"),
        pytest.param(NOTE_STARTED, make_response(401), id="note-poll-unauthorized"),
        pytest.param(
            NOTE_STARTED,
            make_response(200, {"last_status": "failed", "failed_reason": "boom"}),
            id="note-workflow-failed",
        ),
    ],
)
def test_activate_returns_circuit_once_create_completed(
    note_post: MagicMock | Exception, note_response: Optional[MagicMock]
) -> None:
    """Once the create workflow completed, no later request may fail activation and orphan the circuit.

    The create process is polled once; a second poll of it would get ``note_response`` and fail the test.
    """
    backend = make_backend(oauth2_active=False)
    completed_create = make_response(
        200, {"last_status": "completed", "current_state": {"subscription": {"subscription_id": "sub-1"}}}
    )
    with (
        patch("supa.nrm.backends.wfo.sleep"),
        patch("supa.nrm.backends.wfo.get", side_effect=[completed_create, note_response]),
        patch("supa.nrm.backends.wfo.post", side_effect=[note_post]),
        patch.object(backend, "_workflow_create", return_value={"id": "create"}),
        patch.object(backend, "_get_global_reservation_id", return_value="global reservation id"),
    ):
        assert backend.activate(UUID(int=1), 1000, "port-1", 100, "port-2", 100, "") == "sub-1"


def test_activate_create_workflow_failure_raises_nsi_exception() -> None:
    """A failed create workflow still fails activation: there is no circuit to keep."""
    backend = make_backend(oauth2_active=False)
    failed = make_response(200, {"last_status": "failed", "failed_reason": "vlan in use"})
    with (
        patch("supa.nrm.backends.wfo.sleep"),
        patch("supa.nrm.backends.wfo.get", return_value=failed),
        patch.object(backend, "_workflow_create", return_value={"id": "create"}),
        patch.object(backend, "_add_note") as mock_add_note,
    ):
        with pytest.raises(NsiException):
            backend.activate(UUID(int=1), 1000, "port-1", 100, "port-2", 100, "")
    mock_add_note.assert_not_called()
