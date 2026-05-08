# SuPA MCP Server

A read-only [Model Context Protocol](https://modelcontextprotocol.io/) server embedded in `supa serve`. It exposes NSI circuit data to LLM agents via streamable HTTP, enabling agent workflows that need to inspect circuit status or retrieve endpoint device and interface information.

## Tools

### `list_circuits`

Lists all circuits with optional state filtering. Returns a JSON array of circuit summaries.

Each entry includes `connection_id` (UUID), `description`, `global_reservation_id`, `create_date`, and four state machine values:

| State field | Values |
|---|---|
| `reservation_state` | `RESERVE_START` \| `RESERVE_CHECKING` \| `RESERVE_HELD` \| `RESERVE_COMMITTING` \| `RESERVE_FAILED` \| `RESERVE_TIMEOUT` \| `RESERVE_ABORTING` |
| `provision_state` | `RELEASED` \| `PROVISIONING` \| `PROVISIONED` \| `RELEASING` |
| `lifecycle_state` | `CREATED` \| `FAILED` \| `TERMINATING` \| `PASSED_END_TIME` \| `TERMINATED` |
| `data_plane_state` | `DEACTIVATED` \| `AUTO_START` \| `ACTIVATING` \| `ACTIVATED` \| `AUTO_END` \| `DEACTIVATING` \| `ACTIVATE_FAILED` \| `DEACTIVATE_FAILED` \| `UNHEALTHY` |

Any combination of state filters can be passed, e.g. `provision_state="PROVISIONED"` to find active circuits.

### `get_circuit`

Returns full details for a single circuit by UUID. Includes all four state values, bandwidth, schedule (start/end time), STP identifiers, port IDs, VLANs, and `circuit_id` (the NRM backend identifier, present after provisioning).

### `get_circuit_endpoints`

Returns source and destination endpoint information for a circuit. Each endpoint includes:

| Field | Always present | Notes |
|---|---|---|
| `port_id` | yes | NRM port identifier |
| `vlan` | yes | Selected VLAN integer |
| `stp_id` | yes | NSI Service Termination Point URN |
| `device` | only if port mapping configured | Router hostname |
| `interface` | only if port mapping configured | Interface name |

Also returns `circuit_id` and `bandwidth_mbps` at the top level.

This tool is only available after a reservation is committed (i.e. `provision_state` has been initialized). It returns a not-found message for circuits still in early reservation states.

## Configuration

The MCP server is disabled by default. Enable it via environment variable or CLI flag on `supa serve`.

### Environment variables

All variables use the `SUPA_MCP_` prefix and can be set in `supa.env` or the environment.

| Variable | Default | Description |
|---|---|---|
| `SUPA_MCP_ENABLE` | `false` | Set to `true` to start the MCP server |
| `SUPA_MCP_HOST` | `127.0.0.1` | Bind host. Use `0.0.0.0` to expose on all interfaces. |
| `SUPA_MCP_PORT` | `8765` | HTTP port for the MCP endpoint |
| `SUPA_MCP_LOG_LEVEL` | `INFO` | Log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `SUPA_MCP_PORT_MAPPING_FILE` | _(none)_ | Path to a YAML port mapping file (see below) |

### CLI flags

The same settings can be passed directly to `supa serve`:

```
supa serve \
  --mcp-enable \
  --mcp-host 0.0.0.0 \
  --mcp-port 8765 \
  --mcp-port-mapping-file /etc/supa/port_mapping.yaml
```

Passing `--mcp-host` or `--mcp-port` without `--mcp-enable` also enables the server automatically.

### Container deployment

No change to the container `CMD` is required. Set environment variables in the deployment manifest:

```yaml
env:
  - name: SUPA_MCP_ENABLE
    value: "true"
  - name: SUPA_MCP_HOST
    value: "0.0.0.0"
  - name: SUPA_MCP_PORT
    value: "8765"
```

## Endpoints

Once running:

| Path | Description |
|---|---|
| `POST /mcp` | MCP streamable HTTP endpoint (used by MCP clients) |

## MCP client configuration

Example for Claude Desktop or Cursor:

```json
{
  "mcpServers": {
    "supa": {
      "url": "http://127.0.0.1:8765/mcp"
    }
  }
}
```

## Port mapping file

By default, `get_circuit_endpoints` returns `port_id` (the NRM port identifier) for each endpoint but does not resolve it to a router hostname and interface name. A YAML port mapping file provides this static resolution.

### Format

```yaml
port_mapping:
  "<port_id>":
    device: "<router hostname>"
    interface: "<interface name>"
```

### Example

```yaml
port_mapping:
  "urn:ogf:network:example.net:topology:port1":
    device: "router1.example.net"
    interface: "et-0/0/0"
  "urn:ogf:network:example.net:topology:port2":
    device: "router2.example.net"
    interface: "ge-0/0/1"
```

The `port_id` keys must exactly match the values stored in `Connection.src_port_id` / `Connection.dst_port_id` in the SuPA database. You can find the port IDs for a circuit by calling `get_circuit_endpoints` without a mapping file — the `port_id` field is always returned regardless.

A template file is provided at [`port_mapping.example.yaml`](../../../../port_mapping.example.yaml) in the project root.

### Without a mapping file

If no mapping file is configured, `device` and `interface` are simply absent from the endpoint response. The `port_id` is always returned and can be passed to an external tool for resolution.
