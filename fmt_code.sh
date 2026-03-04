#!/usr/bin/env sh

PY_INTERPRETER_PATH=$1
FILE_PATH=$2

echo ======== ruff format ========
${PY_INTERPRETER_PATH} -m ruff format ${FILE_PATH}
echo ======== ruff check ========
${PY_INTERPRETER_PATH} -m ruff check ${FILE_PATH}
echo ======== mypy ========
${PY_INTERPRETER_PATH} -m mypy ${FILE_PATH}
