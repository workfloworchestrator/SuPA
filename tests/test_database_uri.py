"""Tests for keeping the database password out of log lines and help text."""

from unittest.mock import Mock

import click
import pytest
import structlog
from click.testing import CliRunner
from sqlalchemy.exc import OperationalError

from supa import hide_password, init_app, settings
from supa.main import CONTEXT_SETTINGS, database_uri_option

URI_WITH_LOGIN = "postgresql://supa:s3cret@db.example:5432/supa"
MASKED_URI = "postgresql://supa:***@db.example:5432/supa"


@pytest.mark.parametrize(
    ("database_uri", "expected"),
    [
        pytest.param(URI_WITH_LOGIN, MASKED_URI, id="userinfo-password"),
        pytest.param(
            "postgresql://supa@db.example/supa?password=s3cret",
            "postgresql://supa@db.example/supa?password=%2A%2A%2A",
            id="query-password",
        ),
        pytest.param(
            "postgresql://supa@db.example/supa?sslmode=require&sslpassword=k3y",
            "postgresql://supa@db.example/supa?sslmode=require&sslpassword=%2A%2A%2A",
            id="query-sslpassword",
        ),
        pytest.param("sqlite:////tmp/a#b.db", "sqlite:////tmp/a#b.db", id="sqlite-path-kept-verbatim"),
        pytest.param("postgresql://localhost/supa", "postgresql://localhost/supa", id="no-password"),
        pytest.param("localhost/supa", "<unparseable database URI>", id="unparseable"),
        pytest.param("postgresql://supa:s3cret@db.example:badport/supa", "<unparseable database URI>", id="bad-port"),
    ],
)
def test_hide_password(database_uri: str, expected: str) -> None:
    """The password is masked, a URI without one is kept as is, and a bad URI does not raise."""
    assert hide_password(database_uri) == expected


def test_database_uri_option_help_hides_password(monkeypatch: pytest.MonkeyPatch) -> None:
    """``--help`` shows the masked default, never the password in ``settings.database_uri``."""
    monkeypatch.setattr(settings, "database_uri", URI_WITH_LOGIN)

    @click.command(context_settings=CONTEXT_SETTINGS)
    @database_uri_option  # type: ignore[untyped-decorator]
    def command() -> None:
        """Stand in for a sub command that takes the common database option."""

    result = CliRunner().invoke(command, ["--help"])
    help_text = "".join(result.output.split())  # help wraps long values; join the pieces

    assert result.exit_code == 0
    assert "s3cret" not in help_text
    assert MASKED_URI in help_text


def test_init_app_logs_masked_database_uri(monkeypatch: pytest.MonkeyPatch) -> None:
    """The "Create database connection" line carries the masked URI, never the password."""
    monkeypatch.setattr(settings, "database_uri", URI_WITH_LOGIN)
    monkeypatch.setattr(settings, "database_file", None)
    # fail after the line is logged, nothing else runs
    monkeypatch.setattr(
        "supa.create_engine", Mock(side_effect=OperationalError("connect", {}, Exception("connection refused")))
    )

    with structlog.testing.capture_logs() as logs, pytest.raises(SystemExit):
        init_app()

    assert "s3cret" not in str(logs)
    assert {"event": "Create database connection", "database_uri": MASKED_URI, "log_level": "info"} in logs
