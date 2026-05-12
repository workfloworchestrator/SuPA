"""Tests for MCP CLI integration in supa serve."""

from click.testing import CliRunner

from supa.main import cli


def test_serve_has_mcp_enable_flag() -> None:
    """Supa serve --help shows the --mcp-enable flag."""
    runner = CliRunner()
    result = runner.invoke(cli, ["serve", "--help"])
    assert result.exit_code == 0
    assert "--mcp-enable" in result.output


def test_serve_help_exits_cleanly() -> None:
    """Supa serve --help exits with code 0."""
    runner = CliRunner()
    result = runner.invoke(cli, ["serve", "--help"])
    assert result.exit_code == 0
