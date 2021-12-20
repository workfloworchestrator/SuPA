#!/usr/bin/env sh

PY_INTERPRETER_PATH=$1
FILE_PATH=$2

echo ======== black ========
${PY_INTERPRETER_PATH} -m black ${FILE_PATH}
echo ======== isort ========
${PY_INTERPRETER_PATH} -m isort ${FILE_PATH}
echo ======== flake8 ========
${PY_INTERPRETER_PATH} -m flake8 ${FILE_PATH}
echo ======== mypy ========
${PY_INTERPRETER_PATH} -m mypy ${FILE_PATH}
