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

All settings live in the global SuPA `Settings` class and can be set in `supa.env`
or as environment variables, alongside every other SuPA setting. Names are
case-insensitive — `mcp_enable`, `MCP_ENABLE`, and `Mcp_Enable` all resolve to the
same field. Lowercase matches `supa.env` style; uppercase is conventional in
Kubernetes/container manifests.

| Variable | Default | Description |
|---|---|---|
| `mcp_enable` | `false` | Set to `true` to start the MCP server |
| `mcp_host` | `127.0.0.1` | Bind host. Use `0.0.0.0` to expose on all interfaces. |
| `mcp_port` | `8765` | HTTP port for the MCP endpoint |
| `mcp_log_level` | `INFO` | Log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `mcp_port_mapping_file` | _(none)_ | Path to a YAML port mapping file (see below) |

### CLI flags

The same settings can be passed directly to `supa serve`:

```
supa serve \
  --mcp-enable \
  --mcp-host 0.0.0.0 \
  --mcp-port 8765 \
  --mcp-port-mapping-file /etc/supa/port_mapping.yaml
```

The server only starts when `mcp_enable` is true — passing `--mcp-host` or `--mcp-port` on their own changes the bind address but does not enable the server.

### Container deployment

No change to the container `CMD` is required. Set environment variables in the deployment manifest:

```yaml
env:
  - name: MCP_ENABLE
    value: "true"
  - name: MCP_HOST
    value: "0.0.0.0"
  - name: MCP_PORT
    value: "8765"
```

## Endpoints

Once running:

| Path | Description |
|---|---|
| `POST /mcp` | MCP streamable HTTP endpoint (used by MCP clients) |

## Kubernetes probes

The container `livenessProbe` and `readinessProbe` in the Helm chart hit `/healthcheck` on the document-server port. They do **not** cover the MCP port — if the MCP server crashes, the pod stays `Ready` and Kubernetes will not restart it. A second `httpGet` probe is not an option (each container only allows one of each probe type), and FastMCP does not expose a health-check route that returns a 2xx on `GET`.

If you need MCP-aware health checking, run an external probe (for example a CronJob that issues `POST /mcp` with a `tools/list` request) and alert on failure.

## Security

The MCP endpoint has **no authentication** — any client that can reach the listening socket can invoke every tool and read every circuit record SuPA has. The tools are read-only, but circuit data includes endpoint identifiers, VLANs, schedules, and (with a port mapping file) device hostnames and interface names.

Operational guidance:

- The default bind address is `127.0.0.1`. Do not change it to `0.0.0.0` unless you also restrict access in front of SuPA.
- In the Helm chart the bind address is `0.0.0.0` and a ClusterIP `Service` (`<release>-mcp`) is created. Ingress is not provisioned, so by default the endpoint is in-cluster only — but any pod in the cluster can reach it. Add a `NetworkPolicy` selecting just the intended clients before exposing it to a shared cluster.
- Do not put the endpoint behind a public ingress without an authenticating proxy in front of it.

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
