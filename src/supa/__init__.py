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
import logging.config
import sys
from enum import Enum
from pathlib import Path

import structlog
from pydantic import BaseSettings

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
            "file": {
                "level": "DEBUG",
                "class": "logging.handlers.WatchedFileHandler",
                "filename": "supa.log",
                "formatter": "plain",
            },
        },
        "loggers": {
            "": {"handlers": ["default", "file"], "level": "DEBUG", "propagate": True},
            # Set `level` to `INFO` or `DEBUG` here for detailed SQLAlchemy logging.
            "sqlalchemy.engine": {"handlers": ["default", "file"], "level": "WARN", "propagate": False},
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

    max_workers: int = 10
    insecure_address_port: str = "[::]:50051"
    database_journal_mode: JournalMode = JournalMode.WAL
    database_file: Path = Path("supa.db")

    class Config:  # noqa: D106
        case_sensitive = True


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


settings = Settings(_env_file=resolve_env_file())
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
