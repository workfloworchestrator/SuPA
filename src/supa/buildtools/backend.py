#  Copyright 2020-2025 SURF.
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
"""Distutils/setuptools packaging information file."""

import importlib
import operator
import sys
from fileinput import FileInput
from os import PathLike
from pathlib import Path
from typing import Mapping

import setuptools.build_meta as _build_meta

# The absolute path of SuPA's root package.
ROOT_PKG_PATH = Path(__file__).resolve().parent.parent

# Relative path (to SuPA's root package) of the package that will contain the protobuf/gRPC generated code.
GEN_CODE_REL_PKG_PATH = Path("grpc_nsi")

# The absolute path of where we expect the protobuf/gRPC definitions to live.
PROTOS_PATH = (ROOT_PKG_PATH / "protos").resolve(strict=True)


def _compile_protos() -> None:
    try:
        # With help of PEP-518 and the `build-system` configuration in `pyproject.toml`, `pip install -e .` will
        # pre-install this for us before this code is run. Hence the import should not fail.
        import grpc_tools.protoc
    except ImportError as ie:
        # Though should it fail for some magical reason, it doesn't hurt to help the user with manual instructions.
        raise RuntimeError(
            "Before installing 'supa', run: pip install setuptools wheels grpcio-tools~=1.29 "
            "(Check exact version number in `pyproject.toml`. Needs to be the same as that of `grpcio`)"
        ) from ie

    gen_code_path = ROOT_PKG_PATH / GEN_CODE_REL_PKG_PATH
    gen_code_path.mkdir(exist_ok=True)

    # Include common gRPC protobuf definitions
    proto_include = importlib.resources.files("grpc_tools") / "_proto"

    proto_files = list(PROTOS_PATH.glob("*.proto"))
    if len(proto_files) == 0:
        raise RuntimeError(
            f"Could not find any protobuf files in directory {PROTOS_PATH}. Hence no Python code to generate."
        )
    # The protoc compiler (with gRPC plugin) seem to only accept one proto file at a time
    for pf in proto_files:
        exit_code = grpc_tools.protoc.main(
            [
                "grpc_tools.protoc",
                f"--proto_path={proto_include}",
                f"--proto_path={PROTOS_PATH}",
                f"--python_out={gen_code_path}",
                f"--grpc_python_out={gen_code_path}",
                f"--mypy_out={gen_code_path}",
                pf.as_posix(),
            ]
        )
        if exit_code != 0:
            raise RuntimeError(f"Could not generate Python code from protobuf file {pf}. Exit code: {exit_code}")

    # Post process generated Python modules to fix imports of generated modules.
    #
    # The generated Python modules 'think' they are part of the root package whereas in reality they
    # are part of a subpackage. This means that if one generated module imports another generated module
    # by means of:
    #
    #    import fubar_pb2 as fubar__pb2
    #
    # it will fail. To correct this we can rewrite that import using relative imports. That way we do
    # no need to know the exact subpackage we are in. So changing the import statement above to:
    #
    #    from . import fubar_pb2 as fubar__pb2
    #
    # We solve the problem.
    py_proto_files = tuple(gen_code_path.glob("*.py"))
    py_proto_modules = tuple(map(operator.attrgetter("stem"), py_proto_files))
    with FileInput(files=tuple(map(str, py_proto_files)), inplace=True) as ppf:
        for line in ppf:
            for mod in py_proto_modules:
                if mod in line:
                    line = line.replace(f"import {mod}", f"from . import {mod}")
            # FileInput, with `inplace` set to `True` redirects stdout to the file currently being
            # processed.
            sys.stdout.write(line)

    # The generated code should be part of a package
    (gen_code_path / "__init__.py").touch(mode=0o644, exist_ok=True)


def build_wheel(
    wheel_directory: str | PathLike[str],
    config_settings: Mapping[str, str | list[str] | None] | None = None,
    metadata_directory: str | PathLike[str] | None = None,
) -> str:
    """Overload build_wheel from setuptools to prepend compile protos step."""
    _compile_protos()
    return _build_meta.build_wheel(wheel_directory, config_settings, metadata_directory)


def build_sdist(
    sdist_directory: str | PathLike[str],
    config_settings: Mapping[str, str | list[str] | None] | None = None,
) -> str:
    """Overload build_sdist from setuptools to prepend compile protos step."""
    _compile_protos()
    return _build_meta.build_sdist(sdist_directory, config_settings)


def build_editable(
    wheel_directory: str | PathLike[str],
    config_settings: Mapping[str, str | list[str] | None] | None = None,
    metadata_directory: str | PathLike[str] | None = None,
) -> str:
    """Overload build_editable from setuptools to prepend compile protos step."""
    _compile_protos()
    return _build_meta.build_editable(wheel_directory, config_settings, metadata_directory)


if __name__ == "__main__":
    _compile_protos()
    sys.exit(0)
