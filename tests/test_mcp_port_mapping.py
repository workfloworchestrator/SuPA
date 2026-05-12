"""Tests for the port mapping module."""

import textwrap
from pathlib import Path

import pytest

from supa.mcp.port_mapping import PortResolver


@pytest.fixture
def mapping_yaml(tmp_path: Path) -> Path:
    """Create a temporary YAML port mapping file."""
    content = textwrap.dedent("""\
        port_mapping:
          "port-a1":
            device: "router1.example.net"
            interface: "ge-0/0/1"
          "port-b2":
            device: "router2.example.net"
            interface: "et-0/0/2"
    """)
    f = tmp_path / "port_mapping.yaml"
    f.write_text(content)
    return f


def test_resolve_known_port(mapping_yaml: Path) -> None:
    """Known port_id resolves to device and interface."""
    resolver = PortResolver(mapping_yaml)
    result = resolver.resolve("port-a1")
    assert result == {"device": "router1.example.net", "interface": "ge-0/0/1"}


def test_resolve_unknown_port(mapping_yaml: Path) -> None:
    """Unknown port_id returns empty dict."""
    resolver = PortResolver(mapping_yaml)
    result = resolver.resolve("port-unknown")
    assert result == {}


def test_resolve_no_mapping_file() -> None:
    """PortResolver with None file returns empty dict for any port."""
    resolver = PortResolver(None)
    result = resolver.resolve("port-a1")
    assert result == {}


def test_resolve_missing_file(tmp_path: Path) -> None:
    """PortResolver with nonexistent file path returns empty dict."""
    resolver = PortResolver(tmp_path / "nonexistent.yaml")
    result = resolver.resolve("port-a1")
    assert result == {}
