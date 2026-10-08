# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

SuPA (SURF ultimate Provider Agent) implements the NSI Connection Service v2.1 protocol via gRPC for managing network circuit reservations across federated R&E network providers. It uses a PolyNSI companion project as a SOAP-to-gRPC proxy rather than implementing SOAP directly.

## Common Commands

```bash
# Setup
uv sync --link-mode=copy --dev        # Install dependencies
pre-commit install                      # Enable git hooks

# Linting & formatting
uv run ruff format src/supa tests
uv run ruff check src/supa tests
uv run mypy src/supa
uv run mypy tests                       # Run separately from src

# Testing
uv run pytest tests                     # All tests
uv run pytest tests/path/test_file.py::test_name  # Single test
uv run pytest --cov-report term-missing --cov=src tests  # With coverage
TEST_DATABASE_URI=postgresql://localhost/supa-test uv run pytest tests  # On PostgreSQL; drops and recreates that database

# Run the application
uv run supa serve

# Regenerate protobuf/gRPC Python code from .proto files.
# grpcio-tools is a build-time-only dependency, so run it in an isolated env rather than the project venv,
# at the version pinned in [build-system].requires:
uv run --isolated --no-project --with grpcio-tools==1.84.0 --with mypy-protobuf --with setuptools \
  python src/supa/buildtools/backend.py

# Build documentation
uv sync --link-mode=copy --group dev --group doc
make -C docs html
```

## Architecture

### Core Flow

gRPC requests arrive at `connection/provider/server.py`, which schedules background jobs (`job/`) via APScheduler. Jobs execute state machine transitions (`connection/fsm.py`) and persist state to the database (`db/model.py`). Callbacks to the requesting NSA go through `connection/requester.py`.

### State Machines

Four FSMs in `connection/fsm.py` govern each connection's lifecycle, all inheriting from `SuPAStateMachine`:
- **ReservationStateMachine** — reserve, commit, abort, timeout
- **ProvisionStateMachine** — provision, release
- **LifecycleStateMachine** — create, terminate, endtime, failed
- **DataPlaneStateMachine** — activate, deactivate, auto-start/end, health checks

### Network Resource Manager Backends

Pluggable backends in `nrm/backends/` implement `nrm/backend.py:BaseBackend`. Available: `example` (reference), `wfo`, `ciena8190`, `nso`. Selected via `backend` setting in `supa.env`.

`wfo` talks to any orchestrator-core Workflow Orchestrator: workflows and domain models over REST, subscription lookups (STP list by product tag, circuit status for the health check) over GraphQL. Do not use `/api/subscriptions/search` for lookups: it reads the `subscriptions_search` materialized view, whose refresh core throttles to once per 120 s, so a subscription that went active within that window stays indexed as `provisioning` until the next write. Everything except the create form (`_create_form`) and the STP mapping (`_stp_from_domain_model`) is product-agnostic; site-specific products subclass those two methods in a module on `PYTHONPATH`. Its settings live in `wfo.env` with a `wfo_` env prefix.

### Custom Build Backend

`src/supa/buildtools/backend.py` implements PEP 517/518 hooks that auto-compile `.proto` files (in `protos/`) to Python (in `grpc_nsi/`) using `grpc_tools.protoc` and post-processes imports. `grpcio-tools` lives only in `[build-system].requires` (the isolated build env), not in the runtime/dev dependencies. Keep it at the same version as the runtime `grpcio`: the generated `*_pb2_grpc.py` code raises at import when `grpcio` is older than the `grpcio-tools` that generated it.

### Configuration

Pydantic Settings class in `src/supa/__init__.py` with precedence: CLI args > env vars > `supa.env` > defaults. Key settings: database URI, gRPC host/port, backend selection, NSA identity.

### Database

SQLAlchemy ORM with composite/natural keys. Default SQLite (WAL mode), optional PostgreSQL via `database_uri`, through psycopg 3 (SQLAlchemy 2.1's default driver for `postgresql://`). CI runs the unit tests on both. Core chain: Connection -> Reservation (1:N) -> Request -> Schedule, plus P2PCriteria, Topology, STP tables.

### Web Server

CherryPy serves NSI Discovery and Topology XML documents on a separate HTTP port from the gRPC server.

## Versioning

The version is the git tag; never edit it. `pyproject.toml` is `dynamic = ["version"]` with
setuptools-scm, so a tag builds `0.5.2` and any other commit builds `0.5.3.dev<n>+g<sha>`. The
container build has no `.git`, so `build-push-container.yml` resolves the version on the runner and
passes `--build-arg VERSION`, which the `Dockerfile` exports as
`SETUPTOOLS_SCM_PRETEND_VERSION_FOR_SUPA`. Omitting it fails the build by design. `uv.lock` records
the project as `(dynamic)` and so does not churn per commit.

## Dependency cooldown

`exclude-newer = "8 days"` in `pyproject.toml` and `minimumReleaseAge` in `.github/renovate.json`
must stay equal. uv enforces the cooldown on indirect dependencies, which Renovate cannot. An urgent
fix younger than that needs a temporary `exclude-newer-package = { <pkg> = false }`.

## Code Style

- **Line length**: 120 characters
- **Type hints**: Required on all function signatures (mypy strict)
- **Docstrings**: Google style (enforced by ruff D rules)
- **Ruff rules**: A, B, C4, D, E, F, G, I, ISC, S, T20, W
- **Pre-commit mypy** excludes `tests/` and `src/supa/nrm/backends/nso_service_model/`
- Generated code in `grpc_nsi/` has relaxed mypy rules — don't manually edit these files
