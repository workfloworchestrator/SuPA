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
"""Setup the DB, configure SQLAlchemy and define the schema.

Due to SuPA's modest DB requirements we have chosen to use `SQLite <https://sqlite.org/index.html>`_.
It is very easy to use,
does not require a full client/server setup,
and it is wickedly fast.
There are some limitations with regards to concurrency,
but those will not affect SuPA with its low DB WRITE needs;
especially when configured with the :attr:`~supa.JournalMode.WAL` journal mode.

"""
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from sqlalchemy import Column, event, inspect
from sqlalchemy.dialects import sqlite
from sqlalchemy.engine import Dialect, Engine
from sqlalchemy.exc import DontWrapMixin
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session
from sqlalchemy.orm.state import InstanceState
from sqlalchemy.pool import _ConnectionRecord
from sqlalchemy.types import TypeDecorator

from supa import settings

logger = structlog.get_logger(__name__)


@event.listens_for(Engine, "connect")  # type: ignore
def set_sqlite_pragma(dbapi_connection: sqlite3.Connection, connection_record: _ConnectionRecord) -> None:
    """Configure certain SQLite settings.

    These settings,
    issued as SQLite `pragmas <https://sqlite.org/pragma.html>`_,
    need to be configured on each connection.
    Hence the usage of SQLAlchemy's engine's connect event.
    """
    with closing(dbapi_connection.cursor()) as cursor:
        # https://sqlite.org/pragma.html#pragma_foreign_keys
        foreign_keys = "ON"
        log = logger.bind(foreign_keys=foreign_keys)
        cursor.execute(f"PRAGMA foreign_keys={foreign_keys}")

        # https://sqlite.org/pragma.html#pragma_auto_vacuum
        auto_vacuum = "INCREMENTAL"
        log = log.bind(auto_vacuum=auto_vacuum)
        cursor.execute(f"PRAGMA auto_vacuum={auto_vacuum}")

        # https://sqlite.org/pragma.html#pragma_journal_mode
        log = log.bind(journal_mode=settings.database_journal_mode.value)
        cursor.execute(f"PRAGMA journal_mode={settings.database_journal_mode.value}")
        log.debug("Set default options for SQLite database.")


class UUID(TypeDecorator):
    """Implement SQLAlchemy UUID column type for SQLite databases.

    This stores Python :class:`uuid.UUID` types as strings (``CHAR(36)``) in the database.
    We have chosen to store the :meth:`uuid.UUID.__str__` representation directly,
    eg. with ``"-"`` between the UUID fields,
    for improved readability.
    """

    impl = sqlite.CHAR(36)

    def process_bind_param(self, value: Optional[uuid.UUID], dialect: Dialect) -> Optional[str]:  # noqa: D102
        if value is not None:
            if not isinstance(value, uuid.UUID):
                raise ValueError(f"'{value}' is not a valid UUID.")
            return str(value)
        return value

    def process_result_value(self, value: Optional[str], dialect: Dialect) -> Optional[uuid.UUID]:  # noqa: D102
        if value is None:
            return value
        return uuid.UUID(value)


class ReprBase:
    """Custom SQLAlchemy model to provide meaningful :meth:`__str__` and :meth:`__repr__` methods.

    Writing appropriate ``__repr__`` and ``__str__`` methods
    for all your SQLAlchemy ORM models
    gets tedious very quickly.
    By using SQLAlchemy's
    `Runtime Inspection API
    <https://docs.sqlalchemy.org/en/latest/core/inspection.html?highlight=runtime inspection api>`_
    this base class can easily generate these methods for you.

    .. note:: This class cannot be used as a regular Python base class
              due to assumptions made by ``declarative_base``. See **Usage** below instead.

    Usage::

        Base = declarative_base(cls=ReprBase)
    """

    def __repr__(self) -> str:
        """Return string that represents a SQLAlchemy ORM model."""
        inst_state: InstanceState = inspect(self)
        attr_vals = [f"{attr.key}={getattr(self, attr.key)}" for attr in inst_state.mapper.column_attrs]
        return f"{self.__class__.__name__}({', '.join(attr_vals)})"

    def __str__(self) -> str:
        """Return string that represents a SQLAlchemy ORM model."""
        return self.__repr__()


class UtcTimestampException(Exception, DontWrapMixin):
    """Exception class for custom UtcTimestamp SQLAlchemy column type."""

    pass


class UtcTimestamp(TypeDecorator):
    """Custom SQLAlchemy column type for storing timestamps in UTC in SQLite databases.

    This column type always returns timestamps with the UTC timezone.
    It also guards against accidentally trying to store Python naive timestamps
    (those without a time zone).

    In the SQLite database the timestamps are stored as strings of format: ``yyyy-mm-dd hh:mm:ss``.
    UTC is always implied.
    """

    impl = sqlite.DATETIME(truncate_microseconds=True)

    def process_bind_param(self, value: Optional[datetime], dialect: Dialect) -> Optional[datetime]:  # noqa: D102
        if value is not None:
            if value.tzinfo is None:
                raise UtcTimestampException(f"Expected timestamp with tzinfo. Got naive timestamp {value!r} instead")
            return value.astimezone(timezone.utc)
        return value

    def process_result_value(self, value: Optional[datetime], dialect: Dialect) -> Optional[datetime]:  # noqa: D102
        if value is not None:
            if value.tzinfo is not None:
                return value.astimezone(timezone.utc)
            return value.replace(tzinfo=timezone.utc)
        return value


# Using type ``Any`` because: https://github.com/python/mypy/issues/2477
Base: Any = declarative_base(cls=ReprBase)


class Connection(Base):
    """DB mapping for registering NSI connections.

    This concerns both reserved, yet not existing, connections
    and existing connections.
    """

    __tablename__ = "connections"

    connection_id = Column(UUID, primary_key=True)


class UnconfiguredSession(scoped_session):
    """Fail safe fake session class to guard against premature SQLAlchemy session usage.

    SQLAlchemy's engine,
    and hence session,
    can only be initialized after all settings have been resolved.
    This means that we cannot initialize it at the module level.
    After all,
    at the time this module is being executed the default settings
    and those of the env file have been processed,
    those specified on the commend line might not have been processed.
    At the same time we want to keep easy access to the :data:`Session` as a module level attribute.
    So we configure the :data:`Session` with this safe guard class
    only to overwrite it with the real thing after command line options have been processed.
    """

    def __init__(self) -> None:  # noqa: D107
        pass

    def __call__(self, *args: Any, **kwargs: Any) -> None:
        """Trap premature ``Session()`` calls and raise an exception."""
        raise Exception(
            """DB has not yet been initialized. Call `main.init_app` first. Only then (locally) import main.db.Session.

IMPORTANT
==========
Make sure you have processed all the different ways of dealing with application
configuration before you call `main.init_app`.  The env file (`supa.env`) and
the environment are handled automatically by the `supa.settings` instance.
However anything specified on the command line generally needs to be processed
explicitly in the module `supa.main`.
"""
        )


Session = UnconfiguredSession()
"""SQLAlchemy Session for accessing the database.

:data:`Session` can only be used after a call to :func:`main.init_app`.
That,
in turn,
can only be called after all application configuration has been resolved,
eg. after command line processing.
:func:`main.init_app` will replace :data:`Session` with a proper SQLAlchemy
(scoped) ``Session``.
"""
