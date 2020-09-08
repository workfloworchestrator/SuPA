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
See also :func:`locate_env_file`
"""
import logging.config
import sys
from pathlib import Path
from typing import Optional

import structlog
from pydantic import BaseSettings

timestamper = structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S")
pre_chain = [
    # Add the log level and a timestamp to the event_dict if the log entry
    # is not from structlog.
    structlog.stdlib.add_log_level,
    timestamper,
]

logging.config.dictConfig(
    {
        "version": 1,
        "disable_existing_loggers": False,
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
                "filename": "test.log",
                "formatter": "plain",
            },
        },
        "loggers": {"": {"handlers": ["default", "file"], "level": "DEBUG", "propagate": True}},
    }
)
structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
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


class Settings(BaseSettings):
    """Application wide settings with default values.

    See also: the ``supa.env`` file
    """

    max_workers: int = 10
    insecure_address_port: str = "[::]:50051"

    class Config:  # noqa: D106
        case_sensitive = True


def locate_env_file() -> Optional[Path]:
    """Locate env file by looking at specific locations.

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

    If none of these locations result in finding the env file we give up.
    ``supa`` will run fine without a configuration file
    as it still has its default values,
    can process environment variables
    and command line arguments.

    Returns:
        The path where the env file was found or ``None``

    """
    # regular pip install env file location
    # TODO we should probably retrieve the exact location from ``setup.cfg`` instead of hardcoding it here.
    data_file_env_file_path = Path(sys.prefix) / "etc" / "supa" / ENV_FILE_NAME

    # editable pip install env file location
    local_env_file_path = Path(__file__).parent.parent.parent / ENV_FILE_NAME  # up from src/supa
    if data_file_env_file_path.exists():
        logger.info("Using pip installed version of env file.", path=str(data_file_env_file_path))
        return data_file_env_file_path
    if local_env_file_path.exists():
        logger.info("Using env file in source tree.", path=str(local_env_file_path))
        return local_env_file_path
    logger.warning(
        "Could not find env file in default locations.", paths=(str(data_file_env_file_path), str(local_env_file_path)),
    )
    return None


settings = Settings(_env_file=locate_env_file())
