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


def test_missing_file_raises(tmp_path: Path) -> None:
    """A configured-but-missing path is operator error, not silently ignored."""
    with pytest.raises(FileNotFoundError):
        PortResolver(tmp_path / "nonexistent.yaml")


@pytest.mark.parametrize(
    "entry",
    [
        '"port-a1":\n    interface: "ge-0/0/1"',  # missing device
        '"port-a1":\n    device: "router1.example.net"',  # missing interface
        '"port-a1": "router1.example.net"',  # not a dict
    ],
)
def test_malformed_entry_raises(tmp_path: Path, entry: str) -> None:
    """An entry missing device/interface (or not a mapping) raises with the port_id."""
    f = tmp_path / "port_mapping.yaml"
    f.write_text(f"port_mapping:\n  {entry}\n")
    with pytest.raises(ValueError, match="port-a1"):
        PortResolver(f)
