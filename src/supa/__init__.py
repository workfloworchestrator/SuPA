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
"""Initial configuration for SuPA.

This being the top level package,
structured logging is configured here
so that it is available everywhere else by means of:

.. code-block:: python

   import structlog
   ...
   logger = structlog.get_logger(__name__)

All possible configurable settings are defined here as part of :class:`Settings`.
All these settings have a default values,
that are overwritten by whatever values those settings have,
if any,
in the configuration file ``supa.env``.
See also :func:`resolve_env_file`
"""
import errno
import functools
import importlib
import logging.config
import platform
import random
import sys
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Union

import pytz
import structlog
from apscheduler.events import EVENT_JOB_ERROR, JobExecutionEvent
from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers.base import BaseScheduler
from apscheduler.util import undefined
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker

from supa.db.model import Base
from supa.job.shared import Job
from supa.util.timestamp import current_timestamp

timestamper = structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S")
pre_chain = [
    # Add the log level, name and a timestamp to the event_dict if the log entry
    # is not from structlog.
    structlog.stdlib.add_log_level,
    structlog.stdlib.add_logger_name,
    timestamper,
]

logging.config.dictConfig(
    {
        "version": 1,
        "disable_existing_loggers": True,
        "formatters": {
            "plain": {
                "()": structlog.stdlib.ProcessorFormatter,
                "processor": structlog.dev.ConsoleRenderer(colors=False),
                "foreign_pre_chain": pre_chain,
            },
            "colored": {
                "()": structlog.stdlib.ProcessorFormatter,
                "processor": structlog.dev.ConsoleRenderer(colors=True),
                "foreign_pre_chain": pre_chain,
            },
        },
        "handlers": {
            "default": {"level": "DEBUG", "class": "logging.StreamHandler", "formatter": "colored"},
            #     "file": {
            #         "level": "DEBUG",
            #         "class": "logging.handlers.WatchedFileHandler",
            #         "filename": "supa.log",
            #         "formatter": "plain",
            #     },
        },
        "loggers": {
            "": {"handlers": ["default"], "level": "DEBUG", "propagate": True},
            # Set `level` to `INFO` or `DEBUG` here for detailed SQLAlchemy logging.
            "sqlalchemy.engine": {"handlers": ["default"], "level": "WARNING", "propagate": False},
        },
    }
)
structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.PositionalArgumentsFormatter(),
        timestamper,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger(__name__)

ENV_FILE_NAME = "supa.env"


def get_project_root() -> Path:
    """Return project root directory.

    Returns:
        project root directory
    """
    return Path(__file__).parent.parent.parent


class JournalMode(str, Enum):
    """A (subset) of the journal modes as supported by SQLite.

    Preferably we should use the :attr:`WAL` journal mode for SQLite
    as that provides the best concurrency;
    allowing for multiple READs to occur while a WRITE is in progress.
    Without WAL,
    as the journal mode,
    SQLite locks the entire database as soon as a transaction starts.
    As SuPA also uses SQLAlchemy,
    that happens to issue a transaction upon session creation,
    this could have a negative performance impact.

    However, :attr:`WAL` journal mode does not work well with networked file systems,
    such as NFS.
    This might also hold for some, or most of the Kubernetes storage volumes.
    If in doubt use a ``local`` volume.

    See also:
        - https://sqlite.org/pragma.html#pragma_journal_mode
        - https://docs.sqlalchemy.org/en/13/dialects/sqlite.html?highlight=sqlite#database-locking-behavior-concurrency
        - https://kubernetes.io/docs/concepts/storage/volumes/#local

    But don't let these warnings fool you.
    SQLlite is a wickedly fast database
    that matches SuPA's needs perfectly.
    """

    WAL = "WAL"
    TRUNCATE = "TRUNCATE"
    DELETE = "DELETE"


class Settings(BaseSettings):
    """Application wide settings with default values.

    See also: the ``supa.env`` file
    """

    model_config = SettingsConfigDict(case_sensitive=True)

    grpc_server_max_workers: int = 8

    grpc_server_insecure_host: str = "localhost"
    grpc_server_insecure_port: str = "50051"
    """The host and port SuPA is listening on."""

    grpc_client_insecure_host: str = "localhost"
    grpc_client_insecure_port: str = "9090"
    """The host and port the Requester Agent/PolyNSI is listening on."""

    document_server_host: str = "localhost"
    document_server_port: int = 4321

    # Each gRPC worker can schedule at least one job, hence the number of scheduler workers should
    # be at least as many as the gRPC ones. We include a couple extra for non-gRPC initiated jobs.
    scheduler_max_workers: int = grpc_server_max_workers + 4

    database_journal_mode: JournalMode = JournalMode.WAL
    database_file: Path = Path("supa.db")

    topology_freshness: int = 60
    log_level: str = ""

    domain: str = "example.domain:2013"
    topology: str = "topology"
    manual_topology: bool = False
    reserve_timeout: int = 120
    backend: str = ""

    nsa_start_time: datetime = current_timestamp()
    nsa_scheme: str = "http"
    nsa_host: str = "localhost"
    nsa_port: str = "8080"
    nsa_name: str = "example.domain uPA"
    nsa_provider_path: str = "/provider"
    nsa_topology_path: str = "/topology"
    nsa_discovery_path: str = "/discovery"
    nsa_owner_timestamp: str = "19700101T000000Z"
    nsa_owner_firstname: str = "Firstname"
    nsa_owner_lastname: str = "Lastname"
    nsa_latitude: str = "-0.374350"
    nsa_longitude: str = "-159.996719"
    topology_name: str = "example.domain topology"

    healthcheck_with_topology: bool = False

    backend_health_check_interval: int = 60

    @property
    def nsa_exposed_url(self) -> str:
        """Return URL that NSA is exposed on constructed from nsa_scheme, nsa_host and nsa_port."""
        return f"{self.nsa_scheme}://{self.nsa_host}:{self.nsa_port}"

    @property
    def nsa_id(self) -> str:
        """Construct NSA ID using Settings.domain."""
        return f"urn:ogf:network:{self.domain}:nsa:supa"


@functools.lru_cache(maxsize=1)  # not for performance, but rather to keep the logging sane.
def resolve_env_file() -> Path:
    """Resolve env file by looking at specific locations.

    Depending on how the project was installed
    we find the env file in different locations.
    When pip performs a regular install
    it will process the ``data_files`` sections in ``setup.cfg``.
    The env file is specified in that section
    and the location specified there (hard coded here) is the first location checked.

    Editable pip installs do not process that section.
    Hence the location of the env file can be found relative to the top level ``supa`` package in the source tree
    (where this code is located).
    This is the second location checked.

    If none of these locations results in finding the env file we give up.

    Returns:
        The path where the env file was found or ``None``

    Raises:
        FileNotFoundError: if the env file could not be resolved/found.

    """
    # regular pip install env file location
    data_file_env_file_path = Path(sys.prefix) / "etc" / "supa" / ENV_FILE_NAME

    # editable pip install env file location
    local_env_file_path = get_project_root() / ENV_FILE_NAME
    if data_file_env_file_path.exists():
        logger.info("Using pip installed version of env file.", path=str(data_file_env_file_path))
        return data_file_env_file_path
    if local_env_file_path.exists():
        logger.info("Using env file in source tree.", path=str(local_env_file_path))
        return local_env_file_path
    raise FileNotFoundError(
        errno.ENOENT,
        "Could not find env file in its default locations.",
        (str(data_file_env_file_path), str(local_env_file_path)),
    )


def resolve_database_file(database_file: Union[Path, str]) -> Path:
    """Resolve the location of the database file.

    SQLite stores its database in a file.
    If the file does not exist,
    it will be created automatically.
    This means that if we get the reference to that file wrong,
    a new one will be created.
    This leads to all kinds of unexpected problems.
    Hence we need a way to predictably resolve the location of the database file.
    :func:`resolve_database_file` uses the following algorithm:

    If ``database_file`` is an absolute path, we are done.
    Otherwise determine if SuPA was installed normally
    or in editable mode/development mode.
    In case of the former
    resolve ``database_file`` relative to ``<venv_dir>/var/db``
    In case of the latter resolve ``database_file`` relative to the project root.

    Args:
        database_file: relative or absolute filename of database file

    Returns:
        Fully resolved/obsolute path name to database file
    """
    if isinstance(database_file, str):
        database_file = Path(database_file)
    if database_file.is_absolute():
        resolved_path = database_file.resolve()
    elif Path(sys.prefix) < resolve_env_file():  # editable install?
        resolved_path = (Path(sys.prefix) / "var" / "db" / database_file).resolve()
    else:
        resolved_path = (get_project_root() / database_file).resolve()
    logger.info(
        "Resolved `database_file`.",
        configured_database_file=str(database_file),
        resolved_database_file=str(resolved_path),
    )
    return resolved_path


settings = Settings(_env_file=resolve_env_file())  # type: ignore[call-arg]
"""Application wide settings.

Initially this only has the settings,
as specified in the env file and environment,
resolved.
Command line processing should overwrite specific settings,
when appropriate,
to reflect that this takes precedence.
As a result you should see code updating :attr:`settings` in most,
if not all,
Click callables (sub commands) defined in :mod:`supa.main`
"""


class UnconfiguredScheduler(BaseScheduler):
    """Fail safe fake scheduler to guard against premature scheduler usage.

    The BackgroundScheduler can only be initialized after all settings have been resolved.
    This means that we cannot initialize it at the module level.
    After all,
    at the time this module is being executed the default settings
    and those of the env file have been processed,
    those specified on the commend line might not have been processed.
    At the same time we want to keep easy access to the :data:`scheduler` as a module level attribute.
    So we configure the :data:`scheduler` with this safe guard class
    only to overwrite it with the real thing after command line options have been processed.
    """

    exc_msg = """Scheduler has not yet been initialized.
Call `main.init_app` first. Only then (locally) import `scheduler`.

IMPORTANT
==========
Make sure you have processed all the different ways of dealing with application
configuration before you call `main.init_app`.  The env file (`supa.env`) and
the environment are handled automatically by the `supa.settings` instance.
However anything specified on the command line generally needs to be processed
explicitly in the module `supa.main`.
"""

    def shutdown(self, wait=True):  # type: ignore
        """Trap premature call and raise an exception."""
        raise Exception(UnconfiguredScheduler.exc_msg)

    def wakeup(self):  # type: ignore
        """Trap premature call and raise an exception."""
        raise Exception(UnconfiguredScheduler.exc_msg)

    def start(self, paused=False):  # type: ignore
        """Trap premature calls and raise an exception."""
        raise Exception(UnconfiguredScheduler.exc_msg)

    def add_job(  # type: ignore
        self,
        func,
        trigger=None,
        args=None,
        kwargs=None,
        id=None,  # noqa: A002
        name=None,
        misfire_grace_time=undefined,
        coalesce=undefined,
        max_instances=undefined,
        next_run_time=undefined,
        jobstore="default",
        executor="default",
        replace_existing=False,
        **trigger_args,
    ):
        """Trap premature calls and raise an exception."""
        raise Exception(UnconfiguredScheduler.exc_msg)


scheduler = UnconfiguredScheduler()
"""Application scheduler for scheduling and executing jobs

:data:`scheduler` can only be used after a call to :func:`main.init_app`.
That,
in turn,
can only be called after all application configuration has been resolved,
eg. after command line processing.
:func:`main.init_app` will replace :data:`scheduler` with a proper ``BackgroundScheduler``.
"""


def _job_error_event_listener(event: JobExecutionEvent) -> None:
    """Catch job execution errors and log warning."""
    try:
        job, connection_id = event.job_id.split("=")
        logger.warning(event.exception.details(), job=job, connection_id=connection_id)
    except ValueError:
        logger.error(event.exception.details())


def init_app(with_scheduler: bool = True) -> None:
    """Initialize the application (database, scheduler, etc) and recover jobs``.

    :func:`init_app` should only be called after **all** application configuration has been resolved.
    Most of that happens implicitly in :mod:`supa`,
    but some of needs to be done after processing command line options.

    For instance, :func:`init_app` assumes :data:`settings`
    (the :attr:`~Settings.database_file` attribute of it)
    has been updated **after** command line processing,
    that is, if the setting was changed on the command line.
    That way the command line options have had the ability
    to override the default values, those of the env file and environment variables.

    .. note:: Only import :data:`supa.db.Session` after the call to :func:`init_app`.
             If imported earlier, :data:`supa.db.Session` will refer to :class:`supa.db.UnconfiguredSession`
             and you will get a nice exception upon usage.

             Likewise only import :data:`scheduler` after the call to :func:`init_app`.
             If imported earlier, :data:`scheduler` will refer to :class:`UnconfiguredScheduler`
             and you will get an equally nice exception.

    If the scheduler is to be initialized as well (see: :attr:`with_scheduler`)
    it will also be started.

    Args:
        with_scheduler: if True, initialize and start scheduler. If False, don't.

    """
    logger.info(
        "Starting SuPA %s using Python %s (%s) on %s"
        % (
            importlib.metadata.version("SuPA"),
            platform.python_version(),
            platform.python_implementation(),
            platform.node(),
        )
    )
    random.seed()

    # Initialize the database
    database_file = resolve_database_file(settings.database_file)
    if not database_file.exists():
        logger.warn(
            "`database_file` did not exist. Created new SQLite DB file. Is this really what you wanted?",
            database_file=database_file,
        )
    engine = create_engine(f"sqlite:///{database_file}", echo=False)

    import supa.db.session

    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    supa.db.session.Session = scoped_session(session_factory)  # type: ignore[assignment]

    import supa.nrm.backend

    if settings.backend:
        sys.path.insert(0, str(get_project_root() / "src" / "supa" / "nrm" / "backends"))
        logger.debug("backend import path", path=sys.path)
        try:
            supa.nrm.backend.backend = __import__(settings.backend).Backend()
        except ModuleNotFoundError:
            logger.warn("cannot find NRM backend module", backend=settings.backend)
        else:
            supa.nrm.backend.backend.log = supa.nrm.backend.backend.log.bind(backend=settings.backend)
            logger.info("successfully loaded NRM backend", backend=settings.backend)

    if with_scheduler:
        # Initialize and start the scheduler
        jobstores = {"default": MemoryJobStore()}
        logger.info("Configuring scheduler executor.", scheduler_max_workers=settings.scheduler_max_workers)
        executors = {"default": ThreadPoolExecutor(settings.scheduler_max_workers)}
        # misfire_grace_time (int) – the time (in seconds) how much this job’s execution is allowed to be late
        # (None means “allow the job to run no matter how late it is”)
        job_defaults = {"coalesce": False, "max_instances": 1, "misfire_grace_time": None}

        global scheduler
        scheduler = BackgroundScheduler(
            jobstores=jobstores, executors=executors, job_defaults=job_defaults, timezone=pytz.utc
        )
        # silence apscheduler logging and only process job error events
        logging.getLogger("apscheduler").setLevel(logging.CRITICAL)
        scheduler.add_listener(_job_error_event_listener, EVENT_JOB_ERROR)
        scheduler.start()

        from supa.job.lifecycle import HealthCheckJob

        scheduler.add_job(job := HealthCheckJob(), trigger=job.trigger(), id=job.job_id, coalesce=True)


def recover_jobs() -> None:
    """Recover jobs from a previous run with_scheduler.

    :func:`recover_jobs` should only be called after :func:`init_app` was called
    and the scheduler is running.

    Try to recover all jobs that did not finish.
    All af SuPA's asynchronous work is performed by jobs that the scheduler schedules.
    If SuPA is terminated before these jobs have had a chance to run to completion,
    they might be recovered by looking at the state of their work in the database.

    See Also: :class:`supa.job.shared.Job`
    """
    recovered_jobs = []
    for job_type in Job.registry:
        recovered_jobs.extend(job_type.recover())
    logger.info("Recovering jobs.", num_recovered_jobs=len(recovered_jobs))
    for job in recovered_jobs:
        scheduler.add_job(job, trigger=job.trigger(), id=job.job_id)
    for job in scheduler.get_jobs():
        next_run_time = job.next_run_time.isoformat()  # type: ignore[attr-defined]
        logger.debug("scheduled job", job=job.id, next_run_time=next_run_time)  # type: ignore[attr-defined]
