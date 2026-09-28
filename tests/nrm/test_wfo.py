"""Unit tests for the WFO NRM backend topology/auth path.

These tests cover the outbound HTTP helpers that the topology refresh depends on
(``_retrieve_access_token``, ``_get_url``, ``_get_nsi_stp_subscription_ids``, ``_is_healthy`` and
``_get_topology``).  All network access is mocked at the module-level ``requests``
``post``/``get`` functions so no real HTTP traffic is made.
"""

from typing import Any, Dict, List, Optional, Type
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest
import structlog
from requests.exceptions import HTTPError, ReadTimeout

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
    """Build a mock ``requests.Response`` that mimics real truthiness (``bool`` == ``ok``)."""
    response = MagicMock(name=f"Response[{status_code}]")
    response.status_code = status_code
    # A real requests.Response is truthy only when status_code < 400 (Response.ok).
    response.__bool__.return_value = status_code < 400
    response.json.return_value = {} if json_data is None else json_data
    if status_code >= 400:
        response.raise_for_status.side_effect = HTTPError(f"{status_code} Error")
    else:
        response.raise_for_status.return_value = None
    return response


@pytest.mark.parametrize(
    ("oauth2_active", "status_code", "json_data", "expected_token"),
    [
        pytest.param(False, None, None, "", id="oauth2-inactive-returns-empty"),
        pytest.param(True, 200, {"access_token": "the-token"}, "the-token", id="success-returns-token"),
        # A 4xx/5xx on the token endpoint makes the Response falsy, so an empty token is
        # returned (no exception): this is what cascades into downstream 401s in production.
        pytest.param(True, 401, None, "", id="unauthorized-returns-empty-token"),
    ],
)
def test_retrieve_access_token_returns_token(
    oauth2_active: bool, status_code: Optional[int], json_data: Optional[Any], expected_token: str
) -> None:
    """``_retrieve_access_token`` returns the bearer token, or empty string when it cannot."""
    backend = make_backend(oauth2_active=oauth2_active)
    with patch("supa.nrm.backends.wfo.post") as mock_post:
        if status_code is not None:
            mock_post.return_value = make_response(status_code, json_data)
        assert backend._retrieve_access_token() == expected_token
        if oauth2_active:
            mock_post.assert_called_once()
        else:
            mock_post.assert_not_called()


def test_retrieve_access_token_timeout_raises_nsi_exception() -> None:
    """A token-endpoint timeout must raise ``NsiException`` rather than a raw ``RequestException``.

    Regression test for the stack-trace-in-logs fix: red before the ``wfo.py`` change (a raw
    ``ReadTimeout`` escapes and is rendered as a CherryPy traceback), green after.
    """
    backend = make_backend()
    with patch("supa.nrm.backends.wfo.post", side_effect=ReadTimeout("read timed out")):
        with pytest.raises(NsiException):
            backend._retrieve_access_token()


def test_get_url_success_returns_response() -> None:
    """``_get_url`` returns the response from an authorised GET."""
    backend = make_backend(oauth2_active=False)
    expected = make_response(200, {"ok": True})
    with patch("supa.nrm.backends.wfo.get", return_value=expected) as mock_get:
        assert backend._get_url("http://nrm.test/api/thing") is expected
        mock_get.assert_called_once()


def test_get_url_request_exception_raises_nsi_exception() -> None:
    """``_get_url`` converts a ``requests`` transport error into an ``NsiException``."""
    backend = make_backend(oauth2_active=False)
    with patch("supa.nrm.backends.wfo.get", side_effect=ReadTimeout("boom")):
        with pytest.raises(NsiException):
            backend._get_url("http://nrm.test/api/thing")


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
        patch.object(backend, "_get_url", return_value=make_response(200, domain_model)),
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
        patch.object(backend, "_get_url", return_value=make_response(404)),
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
