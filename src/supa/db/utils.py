#  Copyright 2025 SURF.
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
"""DB helper functions."""
from sqlalchemy import Text, cast
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.functions import FunctionElement


class group_concat(FunctionElement):
    """Database agnostic group_concat()."""

    name = "group_concat"
    inherit_cache = False


@compiles(group_concat, "sqlite")
def compile_sqlite(element, compiler, **kw):  # type: ignore[no-untyped-def]
    """Sqlite implementation of group_concat(), will just call native Sqlite group_concat()."""
    args = list(element.clauses)
    if len(args) == 1:
        return f"group_concat({compiler.process(args[0])})"
    else:
        return f"group_concat({compiler.process(args[0])}, {compiler.process(args[1])})"


# PostgreSQL version (‼ cast to TEXT here)
@compiles(group_concat, "postgresql")
def compile_postgresql(element, compiler, **kw):  # type: ignore[no-untyped-def]
    """Postgresql implementation of group_concat(), calls PostgreSQL string_agg() with expression cast to Text."""
    args = list(element.clauses)
    expr = args[0]
    sep = "','" if len(args) == 1 else compiler.process(args[1])
    # Cast to text so string_agg works for ANY type
    expr_sql = compiler.process(cast(expr, Text))
    return f"string_agg({expr_sql}, {sep})"
