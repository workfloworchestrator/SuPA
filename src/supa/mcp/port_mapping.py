"""NRM port_id to device/interface mapping from a YAML file."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass
class _PortInfo:
    device: str
    interface: str


class PortResolver:
    """Resolves NRM port_id to device hostname and interface name from a YAML mapping file."""

    def __init__(self, mapping_file: Path | None) -> None:
        """Initialize resolver, optionally loading from a YAML file.

        Args:
            mapping_file: Path to YAML file with port_mapping key, or None to disable.

        Raises:
            FileNotFoundError: ``mapping_file`` is configured but does not exist.
                Silently ignoring a typo means the operator sees no warning while
                every ``get_circuit_endpoints`` call omits ``device``/``interface``.
            ValueError: An entry in the file is missing ``device`` or ``interface``.
        """
        self._mapping: dict[str, _PortInfo] = {}
        if mapping_file is None:
            return
        if not mapping_file.exists():
            raise FileNotFoundError(f"MCP port mapping file does not exist: {mapping_file}")
        self._load(mapping_file)

    def _load(self, path: Path) -> None:
        data = yaml.safe_load(path.read_text())
        entries = (data.get("port_mapping") or {}).items()
        self._mapping = {port_id: self._parse_entry(port_id, info, path) for port_id, info in entries}

    @staticmethod
    def _parse_entry(port_id: str, info: object, path: Path) -> _PortInfo:
        if not isinstance(info, dict) or "device" not in info or "interface" not in info:
            raise ValueError(f"MCP port mapping entry for {port_id!r} in {path} is missing 'device' or 'interface'")
        return _PortInfo(device=info["device"], interface=info["interface"])

    def resolve(self, port_id: str) -> dict[str, str]:
        """Return device and interface for a port_id, or empty dict if not mapped.

        Args:
            port_id: NRM port identifier from Connection.src_port_id or dst_port_id.

        Returns:
            Dict with "device" and "interface" keys, or {} if not found.
        """
        info = self._mapping.get(port_id)
        if info is None:
            return {}
        return {"device": info.device, "interface": info.interface}
