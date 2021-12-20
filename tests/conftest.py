from concurrent import futures

import grpc
import pytest

from supa import init_app, settings
from supa.grpc_nsi import connection_provider_pb2_grpc


@pytest.fixture(autouse=True, scope="session")
def init(tmp_path_factory: pytest.TempPathFactory) -> None:
    """Initialize application and start the connection provider gRPC server."""
    settings.database_file = tmp_path_factory.mktemp("supa") / "supa.db"
    init_app()
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=settings.grpc_server_max_workers))

    # Safe to import, now that `init_app()` has been called
    from supa.connection.provider.server import ConnectionProviderService

    connection_provider_pb2_grpc.add_ConnectionProviderServicer_to_server(ConnectionProviderService(), server)
    server.add_insecure_port(settings.grpc_server_insecure_address_port)

    server.start()
