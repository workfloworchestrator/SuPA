"""Tests for MCP server lifecycle wiring (create/start/serve/stop)."""

from __future__ import annotations

from typing import Generator
from unittest.mock import MagicMock, patch

import pytest
from mcp.server.fastmcp import FastMCP

from supa.mcp import server as mcp_server


@pytest.fixture(autouse=True)
def reset_uvicorn_server() -> Generator[None, None, None]:
    """Reset the module-level _uvicorn_server before and after each test."""
    original = mcp_server._uvicorn_server
    mcp_server._uvicorn_server = None
    yield
    mcp_server._uvicorn_server = original


class TestCreateServer:
    """Tests for create_server."""

    def test_returns_fastmcp_instance(self) -> None:
        """create_server returns a FastMCP instance built from supa.settings."""
        mcp = mcp_server.create_server()
        assert isinstance(mcp, FastMCP)

    @pytest.mark.anyio
    async def test_registers_all_supa_tools(self) -> None:
        """All three SuPA read-only tools are registered on the returned FastMCP."""
        mcp = mcp_server.create_server()
        tools = await mcp.list_tools()
        assert {t.name for t in tools} == {"list_circuits", "get_circuit", "get_circuit_endpoints"}


class TestStopMcp:
    """Tests for stop_mcp."""

    def test_noop_when_no_server_running(self) -> None:
        """stop_mcp is a safe no-op when the server has not been started."""
        assert mcp_server._uvicorn_server is None
        mcp_server.stop_mcp()  # must not raise

    def test_signals_should_exit_when_server_running(self) -> None:
        """stop_mcp flips should_exit on the live uvicorn server."""
        fake_server = MagicMock()
        fake_server.should_exit = False
        mcp_server._uvicorn_server = fake_server
        mcp_server.stop_mcp()
        assert fake_server.should_exit is True


class TestStartMcp:
    """Tests for start_mcp."""

    def test_schedules_one_shot_supa_mcp_job(self) -> None:
        """start_mcp schedules a 'supa-mcp' date job that invokes _serve."""
        fake_scheduler = MagicMock()
        with (
            patch("supa.scheduler", fake_scheduler),
            patch("uvicorn.Server", return_value=MagicMock()),
            patch("uvicorn.Config"),
        ):
            mcp_server.start_mcp()
        fake_scheduler.add_job.assert_called_once()
        kwargs = fake_scheduler.add_job.call_args.kwargs
        assert kwargs["id"] == "supa-mcp"
        assert kwargs["trigger"] == "date"
        assert kwargs["replace_existing"] is True
        assert kwargs["func"] is mcp_server._serve

    def test_populates_module_level_uvicorn_server(self) -> None:
        """start_mcp must set _uvicorn_server so stop_mcp can later find it."""
        fake_server = MagicMock()
        with (
            patch("supa.scheduler"),
            patch("uvicorn.Server", return_value=fake_server),
            patch("uvicorn.Config"),
        ):
            mcp_server.start_mcp()
        assert mcp_server._uvicorn_server is fake_server

    def test_disables_uvicorn_logging_config(self) -> None:
        """uvicorn.Config must receive log_config=None so SuPA's structlog setup is preserved."""
        with (
            patch("supa.scheduler"),
            patch("uvicorn.Server", return_value=MagicMock()),
            patch("uvicorn.Config") as fake_config,
        ):
            mcp_server.start_mcp()
        assert fake_config.call_args.kwargs["log_config"] is None

    def test_raises_uvicorn_access_logger_to_warning(self) -> None:
        """uvicorn.access INFO lines are silenced; warnings/errors still surface."""
        import logging

        access_logger = logging.getLogger("uvicorn.access")
        original_level = access_logger.level
        try:
            access_logger.setLevel(logging.NOTSET)
            with (
                patch("supa.scheduler"),
                patch("uvicorn.Server", return_value=MagicMock()),
                patch("uvicorn.Config"),
            ):
                mcp_server.start_mcp()
            assert access_logger.level == logging.WARNING
        finally:
            access_logger.setLevel(original_level)


class TestServe:
    """Tests for _serve."""

    def test_runs_uvicorn_serve_in_event_loop(self) -> None:
        """_serve forwards the uvicorn server's serve() coroutine to asyncio.run."""
        fake_server = MagicMock()
        fake_coro = MagicMock()
        fake_server.serve.return_value = fake_coro
        mcp_server._uvicorn_server = fake_server
        with patch("asyncio.run") as fake_run:
            mcp_server._serve()
        fake_run.assert_called_once_with(fake_coro)
