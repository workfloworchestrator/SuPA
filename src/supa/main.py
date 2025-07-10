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
import logging
import signal
from concurrent import futures
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from uuid import UUID

import click
import grpc
import sqlalchemy
import structlog
from click import Context, Option
from tabulate import tabulate

from supa import current_timestamp, init_app, recover_jobs, settings
from supa.db.model import P2PCriteria, Schedule
from supa.documents import webengine
from supa.grpc_nsi import connection_provider_pb2_grpc
from supa.util.vlan import VlanRanges

logger = structlog.get_logger(__name__)

CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"], "show_default": True}


# Note: The `type: ignore`'s is the file are their to circumenvent Click's lack of type annotations.


@dataclass
class CommonOptionsState:
    """Class to capture common options shared between Click callables/sub commands."""

    database_file: Optional[Path] = None
    log_level: Optional[str] = None


# Trick from: https://github.com/pallets/click/issues/108
pass_common_options_state = click.make_pass_decorator(CommonOptionsState, ensure=True)
"""Define custom decorator to pass in an CommonOptionState instance as first argument.

When decorating a Click callable/sub command with the :func`common_options` decorator
the Click options defined in that decorator will become part of the sub command
as if they where defined directly on the sub command.
These common options however will not be pass in the argument list to the sub command.
Reason being that we don't know beforehand how many extra common options :func:`common_options` defines,
or if that number later changes possibly breaking existing code.
Instead we want a single state capturing object to be passed in.

Usage::

    @cli.command(context_settings=CONTEXT_SETTINGS)
    @click.option("--fu", ...)
    @click.option("--bar",...)
    @common_options              # <--- usage
    @pass_common_options_state   # <--- usage
    def my_sub_command(common_options: CommonOptionsState, fu: str, bar: str) -> None:
        # explicitly update ``settings`' attributes if they match command line options
        settings.fu = fu
        settings.bar = bar
        ...
        # with all settings resolved, we can now initialize the application properly.
        init_app()

        # actual sub command stuff
        ...
"""


def database_file_option(f):  # type: ignore
    """Define common option for specifying database file location."""

    def callback(ctx: Context, param: Option, value: Optional[str]) -> Optional[str]:
        """Update the Settings instance when the database-file option is used."""
        cos: CommonOptionsState = ctx.ensure_object(CommonOptionsState)
        if value is not None:
            cos.database_file = Path(value)

            # Update the `settings` instance so that it available application wide.
            settings.database_file = cos.database_file
        return value

    return click.option(
        "--database-file",
        type=click.Path(readable=False),
        expose_value=False,  # Don't add to sub command arg list. We have `@pass_common_options_state` for that.
        help="Location of the SQLlite database file",
        callback=callback,
    )(f)


def log_level_option(f):  # type: ignore
    """Define common option for specifying log level."""

    def callback(ctx: Context, param: Option, value: Optional[str]) -> Optional[str]:
        """Update the Settings instance when the database-file option is used."""
        cos: CommonOptionsState = ctx.ensure_object(CommonOptionsState)
        if value in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            cos.log_level = value
            settings.log_level = cos.log_level

            # not certain if this is the best way of setting the log level, but it does seem to do the job
            logging.root.manager.root.setLevel(cos.log_level)
        return value

    return click.option(
        "--log-level",
        type=str,
        expose_value=False,  # Don't add to sub command arg list. We have `@pass_common_options_state` for that.
        help="Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)",
        callback=callback,
        default=settings.log_level,
    )(f)


def common_options(f):  # type: ignore
    """Provide the means to declare common options to Click callables/sub command."""
    f = database_file_option(f)
    f = log_level_option(f)
    return f


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
    "--grpc-server-max-workers",
    default=settings.grpc_server_max_workers,
    type=int,
    help="Maximum number of workers to serve gRPC requests.",
)
@click.option(
    "--grpc-server-insecure-host",
    default=settings.grpc_server_insecure_host,
    help="GRPC server host to listen on.",
)
@click.option(
    "--grpc-server-insecure-port",
    default=settings.grpc_server_insecure_port,
    help="GRPC server port to listen on.",
)
@click.option(
    "--grpc-client-insecure-host",
    default=settings.grpc_client_insecure_host,
    help="Host that PolyNSI listens on.",
)
@click.option(
    "--grpc-client-insecure-port",
    default=settings.grpc_client_insecure_port,
    help="Port that PolyNSI listens on.",
)
@click.option(
    "--document-server-host",
    default=settings.document_server_host,
    help="Host that the document server listens on.",
)
@click.option(
    "--document-server-port",
    default=settings.document_server_port,
    type=int,
    help="Port that the document server listens on.",
)
@click.option(
    "--scheduler-max-workers",
    default=settings.scheduler_max_workers,
    type=int,
    help="Maximum number of workers to execute scheduler jobs.",
)
@click.option("--domain", default=settings.domain, type=str, help="Name of the domain SuPA is responsible for.")
@click.option("--topology", default=settings.topology, type=str, help="Name of the topology SuPA is responsible for.")
@click.option(
    "--manual-topology",
    default=settings.manual_topology,
    is_flag=True,
    help="Use SuPA CLI to manually administrate topology.",
)
@click.option("--reserve-timeout", default=settings.reserve_timeout, type=int, help="Reserve timeout in seconds.")
@click.option("--backend", default=settings.backend, type=str, help="Name of backend module.")
@click.option(
    "--nsa-host",
    default=settings.nsa_host,
    help="Name of the host where SuPA is exposed on.",
)
@click.option(
    "--nsa-port",
    default=settings.nsa_port,
    help="Port where SuPA is exposed on.",
)
@click.option(
    "--nsa-name",
    default=settings.nsa_name,
    help="Descriptive name for this uPA.",
)
@click.option(
    "--nsa-scheme",
    default=settings.nsa_scheme,
    help="URL scheme of the exposed service.",
)
@click.option(
    "--nsa_provider_port",
    default=settings.nsa_provider_port,
    help="Port of the NSI provider endpoint.",
)
@click.option(
    "--nsa-provider-path",
    default=settings.nsa_provider_path,
    help="Path of the NSI provider endpoint.",
)
@click.option(
    "--nsa-topology-path",
    default=settings.nsa_topology_path,
    help="Path of the NSI topology endpoint.",
)
@click.option(
    "--nsa-discovery-path",
    default=settings.nsa_discovery_path,
    help="Path of the NSI discovery endpoint.",
)
@click.option(
    "--nsa-owner-timestamp",
    default=settings.nsa_owner_timestamp,
    help="Timestamp when the owner information was last change.",
)
@click.option(
    "--nsa-owner-firstname",
    default=settings.nsa_owner_firstname,
    help="Firstname of the owner of this uPA.",
)
@click.option(
    "--nsa-owner-lastname",
    default=settings.nsa_owner_lastname,
    help="Lastname of the owner of this uPA.",
)
@click.option(
    "--nsa-latitude",
    default=settings.nsa_latitude,
    help="Latitude of this uPA.",
)
@click.option(
    "--nsa-longitude",
    default=settings.nsa_longitude,
    help="Longitude of this uPA.",
)
@click.option(
    "--topology-name",
    default=settings.topology_name,
    help="Descriptive name for the exposed topology.",
)
@click.option(
    "--topology-freshness",
    default=settings.topology_freshness,
    type=int,
    help="Number of seconds before fetching topology from backend again.",
)
@click.option(
    "--healthcheck-with-topology",
    default=settings.healthcheck_with_topology,
    is_flag=True,
    help="SuPA health check with call to Backend.topology() to assess NRM health.",
)
@click.option(
    "--backend-health-check-interval",
    default=settings.backend_health_check_interval,
    type=int,
    help="The interval between health checks of all active connections in the NRM.",
)
@common_options  # type: ignore
def serve(
    grpc_server_max_workers: int,
    grpc_server_insecure_host: str,
    grpc_server_insecure_port: str,
    grpc_client_insecure_host: str,
    grpc_client_insecure_port: str,
    document_server_host: str,
    document_server_port: int,
    scheduler_max_workers: int,
    domain: str,
    topology: str,
    manual_topology: bool,
    reserve_timeout: int,
    backend: str,
    nsa_host: str,
    nsa_port: str,
    nsa_name: str,
    nsa_scheme: str,
    nsa_provider_port: str,
    nsa_provider_path: str,
    nsa_topology_path: str,
    nsa_discovery_path: str,
    nsa_owner_timestamp: str,
    nsa_owner_firstname: str,
    nsa_owner_lastname: str,
    nsa_latitude: str,
    nsa_longitude: str,
    topology_name: str,
    topology_freshness: int,
    healthcheck_with_topology: bool,
    backend_health_check_interval: int,
) -> None:
    """Start the gRPC server and listen for incoming requests."""
    # Command-line options take precedence.
    settings.grpc_server_max_workers = grpc_server_max_workers
    settings.grpc_server_insecure_host = grpc_server_insecure_host
    settings.grpc_server_insecure_port = grpc_server_insecure_port
    settings.grpc_client_insecure_host = grpc_client_insecure_host
    settings.grpc_client_insecure_port = grpc_client_insecure_port
    settings.document_server_host = document_server_host
    settings.document_server_port = document_server_port
    settings.scheduler_max_workers = scheduler_max_workers
    settings.domain = domain
    settings.topology = topology
    settings.manual_topology = manual_topology
    settings.reserve_timeout = reserve_timeout
    settings.backend = backend
    settings.nsa_host = nsa_host
    settings.nsa_port = nsa_port
    settings.nsa_name = nsa_name
    settings.nsa_scheme = nsa_scheme
    settings.nsa_provider_port = nsa_provider_port
    settings.nsa_provider_path = nsa_provider_path
    settings.nsa_topology_path = nsa_topology_path
    settings.nsa_discovery_path = nsa_discovery_path
    settings.nsa_owner_timestamp = nsa_owner_timestamp
    settings.nsa_owner_firstname = nsa_owner_firstname
    settings.nsa_owner_lastname = nsa_owner_lastname
    settings.nsa_latitude = nsa_latitude
    settings.nsa_longitude = nsa_longitude
    settings.topology_name = topology_name
    settings.topology_freshness = topology_freshness
    settings.healthcheck_with_topology = healthcheck_with_topology
    settings.backend_health_check_interval = backend_health_check_interval

    init_app()

    grpc_server = grpc.server(futures.ThreadPoolExecutor(max_workers=settings.grpc_server_max_workers))

    # Safe to import, now that `init_app()` has been called
    from supa.connection.provider.server import ConnectionProviderService

    connection_provider_pb2_grpc.add_ConnectionProviderServicer_to_server(ConnectionProviderService(), grpc_server)
    grpc_server.add_insecure_port(f"{settings.grpc_server_insecure_host}:{settings.grpc_server_insecure_port}")

    webengine.start()

    grpc_server.start()
    logger.info(
        "Started Connection Provider gRPC Service.",
        grpc_server_max_workers=settings.grpc_server_max_workers,
        grpc_server_insecure_host=settings.grpc_server_insecure_host,
        grpc_server_insecure_port=settings.grpc_server_insecure_port,
    )

    recover_jobs()

    def graceful_shutdown(signum, frame):  # type: ignore [no-untyped-def]
        """Graceful shutdown of SuPA by stopping scheduler, webengine and gRPC server."""
        logger.info("Caught signal, starting graceful shutdown", signal=signum)
        from supa import scheduler

        scheduler.shutdown(wait=True)
        grpc_server.stop(grace=None)
        webengine.graceful()
        webengine.exit()

    signal.signal(signal.SIGINT, graceful_shutdown)
    signal.signal(signal.SIGHUP, graceful_shutdown)
    signal.signal(signal.SIGQUIT, graceful_shutdown)
    signal.signal(signal.SIGTERM, graceful_shutdown)

    grpc_server.wait_for_termination()
    logger.info("Goodbye!")


@cli.group(context_settings=CONTEXT_SETTINGS, help="STP subcommands.")
def stp() -> None:
    """Group all STP subcommands."""
    pass


@stp.command(context_settings=CONTEXT_SETTINGS)
@click.option("--stp-id", required=True, type=str, help="Uniq ID of the STP.")
@click.option("--port-id", required=True, type=str, help="ID of the corresponding port.")
@click.option("--vlans", required=True, type=str, help="VLANs part of this STP.")
@click.option("--description", type=str, help="STP description.")
@click.option("--is-alias-in", type=str, help="Inbound STP ID from connected topology.")
@click.option("--is-alias-out", type=str, help="Outbound STP ID to connected topology.")
@click.option("--bandwidth", required=True, type=int, help="Available bandwidth for this STP in Mbps.")
@click.option("--enabled/--disabled", default=True)
@common_options  # type: ignore
def add(
    stp_id: str,
    port_id: str,
    vlans: str,
    description: Optional[str],
    is_alias_in: Optional[str],
    is_alias_out: Optional[str],
    bandwidth: int,
    enabled: bool,
) -> None:
    """Add STP to topology."""
    init_app(with_scheduler=False)

    # Safe to import, now that `init_app()` has been called
    from supa.db.model import Topology
    from supa.db.session import db_session

    stp = Topology(
        stp_id=stp_id,
        port_id=port_id,
        vlans=str(VlanRanges(vlans)),
        description=description,
        is_alias_in=is_alias_in,
        is_alias_out=is_alias_out,
        bandwidth=bandwidth,
        enabled=enabled,
    )

    try:
        with db_session() as session:
            session.add(stp)
    except sqlalchemy.exc.IntegrityError as error:
        click.echo(f"cannot add STP: {error}", err=True)


@stp.command(context_settings=CONTEXT_SETTINGS)
@click.option("--stp-id", required=True, type=str, help="Uniq ID of the STP.")
@click.option("--port-id", type=str, help="ID of the corresponding port.")
@click.option("--vlans", type=str, help="VLANs part of this STP.")
@click.option("--description", type=str, help="STP description.")
@click.option("--is-alias-in", type=str, help="Inbound STP ID from connected topology.")
@click.option("--is-alias-out", type=str, help="Outbound STP ID to connected topology.")
@click.option("--bandwidth", type=int, help="Available bandwidth for this STP in Mbps.")
@common_options  # type: ignore
def modify(
    stp_id: str,
    port_id: str,
    vlans: str,
    description: Optional[str],
    is_alias_in: Optional[str],
    is_alias_out: Optional[str],
    bandwidth: int,
) -> None:
    """Modify existing STP in topology."""
    init_app(with_scheduler=False)

    # Safe to import, now that `init_app()` has been called
    from supa.db.model import Topology
    from supa.db.session import db_session

    try:
        with db_session() as session:
            stp: Topology = session.query(Topology).filter(Topology.stp_id == stp_id).one()
            if port_id:
                stp.port_id = port_id
            if vlans:
                stp.vlans = vlans
            if description:
                stp.description = description
            if is_alias_in:
                stp.is_alias_in = is_alias_in
            if is_alias_out:
                stp.is_alias_out = is_alias_out
            if bandwidth:
                stp.bandwidth = bandwidth
    except sqlalchemy.orm.exc.NoResultFound:
        click.echo("STP could not be found.", err=True)


@stp.command(name="list", context_settings=CONTEXT_SETTINGS)
@click.option("--only", type=click.Choice(("enabled", "disabled")), help="Limit list of ports [default: list all]")
@common_options  # type: ignore
def stp_list(only: Optional[str]) -> None:
    """List STP's known to this uPA."""
    init_app(with_scheduler=False)
    from supa.db.model import Topology
    from supa.db.session import db_session

    with db_session() as session:
        topology = session.query(Topology)
        if only == "enabled":
            topology = topology.filter(Topology.enabled.is_(True))
        elif only == "disabled":
            topology = topology.filter(Topology.enabled.is_(False))
        stps = topology.with_entities(
            Topology.stp_id,
            Topology.port_id,
            Topology.vlans,
            Topology.description,
            Topology.bandwidth,
            Topology.is_alias_in,
            Topology.is_alias_out,
            Topology.enabled,
        )
        click.echo(
            tabulate(
                tuple(stps),
                headers=(
                    "stp_id",
                    "port_id",
                    "vlans",
                    "description",
                    "bandwidth",
                    "is_alias_in",
                    "is_alias_out",
                    "enabled",
                ),
                tablefmt="psql",
            )
        )


@stp.command(context_settings=CONTEXT_SETTINGS)
@click.option("--stp-id", required=True, type=str, help="STP id to be deleted from topology.")
@common_options  # type: ignore
def delete(stp_id: Optional[UUID]) -> None:
    """Delete STP from topology (if not in use or previously used).

    A STP can only be deleted if it was never used in a reservation.
    Once used  a STP cannot be deleted again.
    A STP can be disabled though!
    This will take it out of the pool of STP's
    reservations (and hence connections) are made against.
    See the `disable` command.
    """
    init_app(with_scheduler=False)
    from supa.db.model import Topology
    from supa.db.session import db_session

    try:
        with db_session() as session:
            stp = session.query(Topology).filter(Topology.stp_id == stp_id).one()
            session.delete(stp)
    except sqlalchemy.exc.IntegrityError:
        click.echo(
            "STP is in use. Could not delete it. (You could disable it instead to prevent further use).", err=True
        )
    except sqlalchemy.orm.exc.NoResultFound:
        click.echo("STP could not be found.", err=True)


def _set_enable(stp_id: str, enabled: bool) -> None:
    """Enable or disable a specific STP."""
    init_app(with_scheduler=False)
    from supa.db.model import Topology
    from supa.db.session import db_session

    try:
        with db_session() as session:
            stp = session.query(Topology).filter(Topology.stp_id == stp_id).one()
            stp.enabled = enabled
            click.echo(f"STP {stp.stp_id} has been {'enabled' if enabled else 'disabled'}.")
    except sqlalchemy.orm.exc.NoResultFound:
        click.echo("STP could not be found.", err=True)


@stp.command(context_settings=CONTEXT_SETTINGS)
@click.option("--stp-id", required=True, type=str, help="STP id to be enabled.")
@common_options  # type: ignore
def enable(stp_id: str) -> None:
    """Expose STP in topology.

    Enabling a STP makes it available for reservation requests.
    """
    _set_enable(stp_id, enabled=True)


@stp.command(context_settings=CONTEXT_SETTINGS)
@click.option("--stp-id", required=True, type=str, help="STP id to be disabled.")
@common_options  # type: ignore
def disable(stp_id: str) -> None:
    """Do not expose STP in topology.

    Disabling a STP makes it unavailable for reservation requests.
    """
    _set_enable(stp_id, enabled=False)


@cli.group(context_settings=CONTEXT_SETTINGS, help="Reservations subcommands.")
def reservation() -> None:
    """Group all reservation subcommands."""
    pass


@reservation.command(name="list", context_settings=CONTEXT_SETTINGS)
@click.option("--only", type=click.Choice(("current", "past")), help="Limit list of reservations [default: list all]")
@click.option(
    "--order-by", type=click.Choice(("start_time", "end_time")), default="start_time", help="Order reservations"
)
@common_options  # type: ignore
def reservation_list(only: Optional[str], order_by: str) -> None:
    """List reservations."""
    init_app(with_scheduler=False)
    from supa.db.model import Reservation
    from supa.db.session import db_session

    with db_session() as session:
        reservations = (
            session.query(Reservation)
            .join(Schedule)
            .join(P2PCriteria)
            # only current schedule and p2p_criteria
            .filter(Schedule.version == Reservation.version, P2PCriteria.version == Reservation.version)
        )
        if only == "current":
            reservations = reservations.filter(Schedule.end_time >= current_timestamp())
        elif only == "past":
            reservations = reservations.filter(Schedule.end_time < current_timestamp())
        if order_by == "start_time":
            reservations = reservations.order_by(Schedule.start_time)
        elif order_by == "end_time":
            reservations = reservations.order_by(Schedule.end_time)
        reservation_entities = reservations.with_entities(
            Reservation.connection_id,
            Reservation.version,
            Schedule.start_time,
            Schedule.end_time,
            P2PCriteria.src_stp_id,
            P2PCriteria.src_selected_vlan,
            P2PCriteria.dst_stp_id,
            P2PCriteria.dst_selected_vlan,
            P2PCriteria.bandwidth,
            Reservation.lifecycle_state,
            Reservation.reservation_state,
            Reservation.provision_state,
            Reservation.data_plane_state,
        )
    click.echo(
        tabulate(
            tuple(reservation_entities),
            headers=(
                "connection id",
                "version",
                "start time",
                "end time",
                "src",
                "vlan",
                "dst",
                "vlan",
                "bw",
                "lifecycle",
                "reservation",
                "provision",
                "dataplane",
            ),
            tablefmt="simple",
        )
    )


@cli.group(context_settings=CONTEXT_SETTINGS, help="Connection subcommands.")
def connection() -> None:
    """Group all connection subcommands."""
    pass


@connection.command(name="list", context_settings=CONTEXT_SETTINGS)
@click.option("--only", type=click.Choice(("current", "past")), help="Limit list of connections [default: list all]")
@click.option(
    "--order-by", type=click.Choice(("start_time", "end_time")), default="start_time", help="Order connections"
)
@common_options  # type: ignore
def connection_list(only: Optional[str], order_by: str) -> None:
    """List connections."""
    init_app(with_scheduler=False)
    from supa.db.model import Connection, Reservation
    from supa.db.session import db_session

    with db_session() as session:
        connections = session.query(Connection).join(Reservation).join(Schedule)
        connections = connections.filter(Schedule.version == Reservation.version)  # only current schedule
        # connections = connections.filter(Connection.circuit_id != None)  # noqa: E711 (needed for NOT NULL clause)
        if only == "current":
            connections = connections.filter(Schedule.end_time >= current_timestamp())
        elif only == "past":
            connections = connections.filter(Schedule.end_time < current_timestamp())
        if order_by == "start_time":
            connections = connections.order_by(Schedule.start_time)
        elif order_by == "end_time":
            connections = connections.order_by(Schedule.end_time)
        connection_entities = connections.with_entities(
            Connection.connection_id,
            Connection.circuit_id,
            Schedule.start_time,
            Schedule.end_time,
            Connection.src_port_id,
            Connection.src_vlan,
            Connection.dst_port_id,
            Connection.dst_vlan,
            Connection.bandwidth,
        )
    click.echo(
        tabulate(
            tuple(connection_entities),
            headers=(
                "connection id",
                "circuit id",
                "start time",
                "end time",
                "src port id",
                "vlan",
                "dst port id",
                "vlan",
                "bw",
            ),
            tablefmt="simple",
        )
    )
