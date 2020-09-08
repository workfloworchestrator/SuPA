#  Copyright 2020 SURF.
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
"""
SuPA main entry point.

SuPA has a single entry point defined in this module,
namely :func:`cli`.
That is what is executed when the ``supa`` command is issued from the command-line.

The other ``@cli.command`` annotated functions in this modules implement the various sub-commands.
"""
from concurrent import futures

import click
import grpc
import structlog

from supa import settings
from supa.connection.provider.server import ConnectionProviderService
from supa.grpc_nsi import connection_provider_pb2_grpc

logger = structlog.get_logger(__name__)

CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"], "show_default": True}


@click.group(context_settings=CONTEXT_SETTINGS)
def cli() -> None:
    """Manage the SURF ultimate Provider Agent from the command line.

    Configuration variables can be set using (in order of precedence):

    \b
    - command line options
    - environment variables
    - entries in `supa.env`

    For more information see `supa.env`.
    """
    pass


@cli.command(context_settings=CONTEXT_SETTINGS)
@click.option(
    "--max-workers", default=settings.max_workers, type=int, help="Maximum number of workers to serve gRPC requests."
)
@click.option("--insecure-address-port", default=settings.insecure_address_port, help="Port to listen on.")
def serve(max_workers: int, insecure_address_port: str) -> None:
    """Starts the gRPC server and listen for incoming requests.

    The requests (messages) it can respond to are implemented in :mod:`supa.connection.provider.server`.
    """
    # Command-line options take precedence.
    settings.max_workers = max_workers
    settings.insecure_address_port = insecure_address_port

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=settings.max_workers))
    log = logger.bind(max_workers=settings.max_workers)

    connection_provider_pb2_grpc.add_ConnectionProviderServicer_to_server(ConnectionProviderService(), server)
    server.add_insecure_port(settings.insecure_address_port)
    log = log.bind(insecure_address_port=settings.insecure_address_port)

    server.start()
    log.info("Started Connection Provider gRPC Service.")

    server.wait_for_termination()
