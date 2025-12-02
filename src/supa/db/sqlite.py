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
"""SQLite specific code."""
import sqlite3
from contextlib import closing

from sqlalchemy import Engine, event
from sqlalchemy.pool import _ConnectionRecord

from supa import settings
from supa.db.session import logger


@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection: sqlite3.Connection, connection_record: _ConnectionRecord) -> None:
    """Configure certain SQLite settings.

    These settings,
    issued as SQLite `pragmas <https://sqlite.org/pragma.html>`_,
    need to be configured on each connection.
    Hence the usage of SQLAlchemy's engine's connect event.
    """
    with closing(dbapi_connection.cursor()) as cursor:
        logger.info("Set SQLite pragma's")
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
