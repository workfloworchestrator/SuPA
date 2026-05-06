"""MCP server configuration via environment variables."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class McpSettings(BaseSettings):
    """MCP server settings. All fields overridable via SUPA_MCP_* environment variables.

    Attributes:
        enable: Start the MCP server when True. Default False.
        host: MCP server bind host. Default 127.0.0.1.
        port: MCP server port. Default 8765.
        log_level: Log level string. Default INFO.
        port_mapping_file: Optional path to YAML port mapping file.
    """

    model_config = SettingsConfigDict(
        env_prefix="SUPA_MCP_",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    enable: bool = False
    host: str = "127.0.0.1"
    port: int = 8765
    log_level: str = "INFO"
    port_mapping_file: Path | None = None
