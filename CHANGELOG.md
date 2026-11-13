# Changelog

All notable changes to SuPA are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Routine dependency
and base-image updates are not listed, except for security fixes.

## [Unreleased]

## [0.6.6] - 2026-11-13

### Added

- `wfo_process_timeout` setting (default 300 s): how long the wfo backend waits for a workflow process.
- Warning when the POST that starts a wfo workflow times out waiting for an answer. It names the
  workflow, the reporter and the POST time, so the process can be found by hand.

### Changed

- wfo: a failed process poll is retried with backoff until the deadline. The wait ends on `completed`,
  `failed`, `aborted`, `api_unavailable`, `inconsistent_data`, `suspended` or `waiting`; any other
  status is polled on.
- wfo: the access token is cached until 60 s before `expires_in`. A rejected cached token is dropped
  and the request is sent once more with a new one. A token response without `expires_in` is not cached.
- wfo: the wait for the `modify_note` process is capped at 30 s.
- wfo: the orchestrator's error detail is the reason of every failed request, not only of create.
- A request that repeats an earlier one (same correlation id, kind and message) is no longer rejected
  with 00101 (NSI CS 2.1 §7.1.3). It is acknowledged as the original was and not processed again, and
  the stored result is sent again. A repeated asynchronous query runs again. The same correlation id
  on a different message is still rejected (#574, fixes #405).
- The `activate` contract is documented in `BaseBackend.activate`.

### Fixed

- wfo: the NRM circuit is kept once the create workflow has completed. A failing `modify_note` step is
  logged and no longer fails the activation, which left the circuit orphaned in the NRM.
- wfo: a non-2xx response to a process poll raised a `KeyError`; it now raises `NsiException`.
- wfo: a token endpoint error returned an empty token; it now raises. A token response without
  `access_token` is rejected.

### Security

- The database password is masked in the startup log line and in the `--database-uri` default shown
  by `--help`.

## [0.6.5] - 2026-10-21

### Security

- certifi 2026.10.19 and Alpine ca-certificates drop the compromised emSign ECC Root CA - G3.

## [0.6.4] - 2026-10-13

### Changed

- Terminate of a reservation that is still `Terminating` runs `TerminateJob` again, once per
  connection, so a requester can retry a terminate. A terminated reservation still answers
  `InvalidTransition`, an unknown one `ReservationNonExistent`.

### Fixed

- ciena8190: terminate treats a circuit that is missing from the device as already deleted.
- An unfiltered query returns all reservations explicitly, no longer through the deprecated empty `or_()`.
- wfo and nso: the log context of a primitive is scoped to a single call and no longer leaks into later
  calls. The misspelt `primitve` key in the wfo health check log context is fixed.

## [0.6.3] - 2026-10-08

### Changed

- `psycopg2-binary` is replaced by `psycopg[binary]` 3.3.6, the default PostgreSQL driver of SQLAlchemy 2.1.
- `ncclient` and `xmltodict` are runtime dependencies, so the container image can run the ciena8190 backend.
- A reservation gets the same VLAN on both ends when one is free on both; otherwise one random VLAN per
  end (#505).
- The unit tests also run on PostgreSQL, selected with `TEST_DATABASE_URI` (#507).
- Indirect dependencies obey the 8-day cooldown through `exclude-newer` in `pyproject.toml` (#489).

### Fixed

- A result registered twice for the same correlation id is replaced instead of failing with a unique
  constraint violation (#501).
- ciena8190: terminate skips the device when the connection was never activated and has no
  `circuit_id` (#500).
- ciena8190: deactivate and terminate read the device again instead of using a cached lookup (#502).

## [0.6.2] - 2026-09-29

### Changed

- The Helm chart renders the config ConfigMap only when `config.filesGlob` or `config.inline` is set;
  otherwise SuPA uses the env files packaged in the image (#486).

## [0.6.1] - 2026-09-29

### Changed

- wfo: subscriptions and the circuit status for the health check are looked up over GraphQL instead of
  the search endpoint, whose materialized view refresh is throttled and could leave a new subscription
  out of the topology (#483).

### Removed

- The `wfo_stp_query` setting, replaced by `wfo_stp_tags` (`|`-separated product tags).

## [0.6.0] - 2026-08-26

### Added

- wfo: the global reservation id is appended to the subscription note.
- wfo: `_create_form()` and `_stp_from_domain_model()` are hooks for subclasses, with an example in the
  module docstring.

### Changed

- **Breaking:** the surf backend is renamed to wfo (`surf.py`, `surf.env` and `test_surf.py` become
  `wfo.*`) and is orchestrator-agnostic.
- **Breaking:** wfo settings use the `wfo_` environment prefix. This frees the global `BASE_URL`,
  `PRODUCT_ID`, `CUSTOMER_ID` and `OIDC_PASSWORD` variables.
- wfo reads the topology from `/api/subscriptions/search`, driven by the new `wfo_stp_query` setting,
  instead of the SURF-only `/api/pythia_legacy` route.
- Helm chart: `oidc_password` moves from `values.yaml` to the secretProviderClass as `WFO_OIDC_PASSWORD`.

### Fixed

- wfo: falls back to `current_state["subscription_id"]` when the workflow does not nest the subscription.

### Security

- wfo no longer logs the bearer token.

## [0.5.3] - 2026-08-25

### Changed

- The version is derived from the git tag with setuptools-scm; `VERSION.txt` is removed.

## [0.5.2] - 2026-08-20

### Added

- The Helm chart is published to `oci://ghcr.io/workfloworchestrator/charts` on release tags.

### Changed

- The MCP server uses the MCP SDK v2 (#446).
- The NSO backend uses httpx2 and python-nso-client 0.2.0.
- The container build runs on semver tags only, not on every tag.

### Security

- starlette 1.3.1 ([CVE-2026-54283](https://nvd.nist.gov/vuln/detail/CVE-2026-54283), #415).
- mcp 1.28.1, python-statemachine 3.2.0 and pydantic-settings 2.14.2, each for a published security
  advisory (#431, #411, #412).

## [0.5.1] - 2026-06-18

### Changed

- A duplicate correlation id is answered with `MissingParameter` (00101) instead of
  `UnsupportedParameter`, per GFD.237 6.3.2 and GFD.235 6.1.

### Fixed

- wfo (then surf): a failed token fetch raises `NsiException` instead of logging a traceback.

## [0.5.0] - 2026-06-02

### Added

- Read-only MCP server in `supa serve`, with the tools `list_circuits`, `get_circuit` and
  `get_circuit_endpoints` for LLM agents (#379). Configured with `mcp_enable`, `mcp_host`, `mcp_port`,
  `mcp_log_level` and `mcp_port_mapping_file`, and in the Helm chart with `mcp.enabled` and
  `mcp.portMapping`. An optional YAML port mapping resolves an NRM port id to a device and interface.
- Ciena 8190 (SAOS 10.x) backend (#265).

### Changed

- Migrated to python-statemachine v3 (#366).
- ruff replaces isort, black and flake8.
- Python 3.11 is no longer supported; Python 3.14 is.

### Security

- pytest 9.0.3, lxml 6.1.0 and cryptography 46.0.7.
- The pip-tools dev dependency is removed (CVE-2026-3219).

## [0.4.4] - 2026-03-03

### Changed

- grpcio is downgraded to 1.78.0 (#332).

## [0.4.3] - 2026-02-24

### Added

- NSO backend: configurable httpx timeouts (#320).

### Changed

- `circuit_id` is generated by the new `provision()` method instead of `activate()`, which takes it as an
  argument. `activate()` and `deactivate()` return `Optional[str]` (#321).
- The Helm chart's `supa.env` uses `org_id` and `nsa_designator` instead of `domain`.

## [0.4.2] - 2026-02-19

### Changed

- **Breaking:** the `domain` setting is replaced by `org_id` and `nsa_designator` (#319).

### Fixed

- NSO backend: optional STP fields in the response are handled (#314).

## [0.4.1] - 2026-01-19

### Changed

- All dependencies are pinned.

### Fixed

- NSO backend: uses the topology from the settings and the correct field names (#298).
- `ProvisionJob` starts other jobs outside its database transaction (#299).

## [0.4.0] - 2025-12-04

No changes since 0.3.6.

## [0.3.6] - 2025-12-04

### Added

- PostgreSQL support next to SQLite, selected with the new `database_uri` option (#294).

### Deprecated

- The database file option, replaced by `database_uri`.

## [0.3.5] - 2025-11-26

### Added

- Editable install support (PEP 660).
- Codecov configuration (#282).

### Changed

- The Dockerfile and the GitHub workflows use uv instead of pip, with Python 3.14.0.

## [0.3.4] - 2025-10-29

### Added

- Environment variable to echo SQL statements.

### Fixed

- "database locked" error: a transaction is always begun explicitly.

## [0.3.3] - 2025-10-08

### Changed

- The surf backend adds more information to its workflow calls (#262).
- The `master` branch is renamed to `main`.

## [0.3.2] - 2025-09-24

### Added

- The `labelSwapping` of the topology `SwitchingService` is configurable.

### Changed

- The NSA provider port is separate from the general NSA port (#254).

## [0.3.1] - 2025-08-05

### Changed

- Extended Helm chart capabilities (#243).

## [0.3.0] - 2025-04-24

### Added

- NSO backend: activate, deactivate and topology (#190).
- Health check of connections in the NRM, with `health_check` in the surf and example backends.

### Changed

- Results and notifications are registered more unambiguously.
- Better database transaction isolation; the reason is shown when a database session rolls back.

### Fixed

- The unhealthy transition is also allowed for auto end connections.

## [0.2.9] - 2025-02-24

### Changed

- The container image is also built for tags and on dispatch.

## [0.2.8] - 2024-12-19

### Added

- All criteria are included in the query output (#163).

### Changed

- The headers of all `Query*` requests are checked.

## [0.2.7] - 2024-11-19

### Added

- `healthcheck_with_topology` setting (#153).

### Fixed

- surf backend: all exceptions are caught while fetching URLs (#148).
- Missing configuration parameters are added to `supa.env`.

## [0.2.6] - 2024-10-02

### Fixed

- The protobuf version matches what grpcio-tools expects.

## [0.2.5] - 2024-09-30

### Added

- Modify reservation (#108).

## [0.2.4] - 2024-07-23

### Changed

- Python 3.12 (#107).

## [0.2.3] - 2024-06-26

### Added

- Arista EOS 4.x backend, based on the OpenNSA backend and untested (#64).
- Unit tests for the topology and discovery document generation (#61).

### Changed

- The surf backend host option is renamed to `base_url` (#92).
- Migrated to SQLAlchemy 2.0 and python-statemachine 1.x, with a better declarative mapping to the
  database (#90).
- surf backend: works with orchestrator-core 2.3.0, whose processes endpoint renamed `status` to
  `last_status` (#94).

## [0.2.2] - 2024-04-03

### Fixed

- surf backend (#32).

## [0.2.1] - 2023-10-03

### Added

- CLI command to modify an STP.
- The request message header is verified, including that SuPA is the targeted providerNSA.

### Fixed

- A query reports auto ending reservations as active as well.

## [0.2.0] - 2023-03-09

### Added

- Implemented messages:
    - connection provider:
        - QueryRecursive
        - QueryNotification
        - QueryNotificationSync
        - QueryResult
        - QueryResultSync
    - connection requester:
        - ErrorEvent
        - QueryRecursiveConfirmed
        - QueryNotificationConfirmed
        - QueryResultConfirmed
- Query summary primitives and the remaining query primitives (#14, #16, #19).
- A results table registers asynchronous messages in the database; notifications are registered with a
  generated unique id.
- `isAlias` in the topology document.
- The version is logged on startup. The discovery and topology paths are configurable.

### Changed

- The CLI commands are regrouped.

### Fixed

- No `last modified` in `QueryConfirmed` when there are no reservations yet.

## [0.1.1] - 2022-12-06

### Added

- Container build workflow (#13).

### Fixed

- Topology update bug (#13).

## [0.1.0] - 2022-07-07

### Added

- Data plane FSM and job to manage connection (de)activation.
- Generation of discovery, topology and healthcheck documents.
- Pluggable backend.
- CLI commands to list reservations and connections.
- Implemented messages:
    - connection provider:
        - Provision
        - Release
        - Terminate
    - connection requester:
        - ProvisionConfirmed
        - ReleaseConfirmed
        - TerminateConfirmed
        - Error
        - DataPlaneStateChange
        - ReserveTimeout

## 0.0.1 - 2020-10-08

### Added

- First release.
- PEP-518 is used to generate Python code from `*.proto` files during installation.
- Advanced Python Scheduler runs `async` processes.
- Reservation system.
- Ports management system (registering the Orchestrator port in SuPA).
- Implemented messages:
    - connection provider:
        - Reserve
        - ReserveCommit
        - ReserveAbort
    - connection requester:
        - ReserveFailed
        - ReserveConfirmed
        - ReserveCommitFailed
        - ReserveCommitConfirmed
        - ReserveAbortConfirmed

[Unreleased]: https://github.com/workfloworchestrator/SuPA/compare/0.6.6...HEAD
[0.6.6]: https://github.com/workfloworchestrator/SuPA/compare/0.6.5...0.6.6
[0.6.5]: https://github.com/workfloworchestrator/SuPA/compare/0.6.4...0.6.5
[0.6.4]: https://github.com/workfloworchestrator/SuPA/compare/0.6.3...0.6.4
[0.6.3]: https://github.com/workfloworchestrator/SuPA/compare/0.6.2...0.6.3
[0.6.2]: https://github.com/workfloworchestrator/SuPA/compare/0.6.1...0.6.2
[0.6.1]: https://github.com/workfloworchestrator/SuPA/compare/0.6.0...0.6.1
[0.6.0]: https://github.com/workfloworchestrator/SuPA/compare/0.5.3...0.6.0
[0.5.3]: https://github.com/workfloworchestrator/SuPA/compare/0.5.2...0.5.3
[0.5.2]: https://github.com/workfloworchestrator/SuPA/compare/0.5.1...0.5.2
[0.5.1]: https://github.com/workfloworchestrator/SuPA/compare/0.5.0...0.5.1
[0.5.0]: https://github.com/workfloworchestrator/SuPA/compare/0.4.4...0.5.0
[0.4.4]: https://github.com/workfloworchestrator/SuPA/compare/0.4.3...0.4.4
[0.4.3]: https://github.com/workfloworchestrator/SuPA/compare/0.4.2...0.4.3
[0.4.2]: https://github.com/workfloworchestrator/SuPA/compare/0.4.1...0.4.2
[0.4.1]: https://github.com/workfloworchestrator/SuPA/compare/0.4.0...0.4.1
[0.4.0]: https://github.com/workfloworchestrator/SuPA/compare/0.3.6...0.4.0
[0.3.6]: https://github.com/workfloworchestrator/SuPA/compare/0.3.5...0.3.6
[0.3.5]: https://github.com/workfloworchestrator/SuPA/compare/0.3.4...0.3.5
[0.3.4]: https://github.com/workfloworchestrator/SuPA/compare/0.3.3...0.3.4
[0.3.3]: https://github.com/workfloworchestrator/SuPA/compare/0.3.2...0.3.3
[0.3.2]: https://github.com/workfloworchestrator/SuPA/compare/0.3.1...0.3.2
[0.3.1]: https://github.com/workfloworchestrator/SuPA/compare/0.3.0...0.3.1
[0.3.0]: https://github.com/workfloworchestrator/SuPA/compare/0.2.9...0.3.0
[0.2.9]: https://github.com/workfloworchestrator/SuPA/compare/0.2.8...0.2.9
[0.2.8]: https://github.com/workfloworchestrator/SuPA/compare/0.2.7...0.2.8
[0.2.7]: https://github.com/workfloworchestrator/SuPA/compare/0.2.6...0.2.7
[0.2.6]: https://github.com/workfloworchestrator/SuPA/compare/0.2.5...0.2.6
[0.2.5]: https://github.com/workfloworchestrator/SuPA/compare/0.2.4...0.2.5
[0.2.4]: https://github.com/workfloworchestrator/SuPA/compare/0.2.3...0.2.4
[0.2.3]: https://github.com/workfloworchestrator/SuPA/compare/0.2.2...0.2.3
[0.2.2]: https://github.com/workfloworchestrator/SuPA/compare/0.2.1...0.2.2
[0.2.1]: https://github.com/workfloworchestrator/SuPA/compare/0.2.0...0.2.1
[0.2.0]: https://github.com/workfloworchestrator/SuPA/compare/0.1.1...0.2.0
[0.1.1]: https://github.com/workfloworchestrator/SuPA/compare/v0.1.0...0.1.1
[0.1.0]: https://github.com/workfloworchestrator/SuPA/releases/tag/v0.1.0
