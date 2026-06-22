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

# Run the application
uv run supa serve

# Regenerate protobuf/gRPC Python code from .proto files.
# grpcio-tools is a build-time-only dependency (it caps protobuf<7, the runtime uses protobuf 7.x),
# so run it in an isolated env rather than the project venv:
uv run --isolated --no-project --with grpcio-tools==1.81.0 --with mypy-protobuf --with setuptools \
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

Pluggable backends in `nrm/backends/` implement `nrm/backend.py:BaseBackend`. Available: `example` (reference), `surf`, `ciena8190`, `nso`. Selected via `backend` setting in `supa.env`.

### Custom Build Backend

`src/supa/buildtools/backend.py` implements PEP 517/518 hooks that auto-compile `.proto` files (in `protos/`) to Python (in `grpc_nsi/`) using `grpc_tools.protoc` and post-processes imports. `grpcio-tools` lives only in `[build-system].requires` (the isolated build env), not in the runtime/dev dependencies: every stable `grpcio-tools` caps `protobuf<7`, so isolating it lets the runtime use protobuf 7.x while the generated (protobuf 6.x) code stays compatible.

### Configuration

Pydantic Settings class in `src/supa/__init__.py` with precedence: CLI args > env vars > `supa.env` > defaults. Key settings: database URI, gRPC host/port, backend selection, NSA identity.

### Database

SQLAlchemy ORM with composite/natural keys. Default SQLite (WAL mode), optional PostgreSQL via `database_uri`. Core chain: Connection -> Reservation (1:N) -> Request -> Schedule, plus P2PCriteria, Topology, STP tables.

### Web Server

CherryPy serves NSI Discovery and Topology XML documents on a separate HTTP port from the gRPC server.

## Code Style

- **Line length**: 120 characters
- **Type hints**: Required on all function signatures (mypy strict)
- **Docstrings**: Google style (enforced by ruff D rules)
- **Ruff rules**: A, B, C4, D, E, F, G, I, ISC, S, T20, W
- **Pre-commit mypy** excludes `tests/` and `src/supa/nrm/backends/nso_service_model/`
- Generated code in `grpc_nsi/` has relaxed mypy rules — don't manually edit these files
