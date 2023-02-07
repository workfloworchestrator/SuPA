"""Distutils/setuptools packaging information file."""
import operator
import shutil
import sys
from distutils.command.clean import clean  # type: ignore
from fileinput import FileInput
from pathlib import Path
from typing import List, Optional, Tuple

import pkg_resources
import setuptools
from setuptools.command.develop import develop
from setuptools.command.install import install

# The absolute path where this project resides.
PROJECT_PATH = Path(__file__).resolve().parent

# The absolute path of SuPA's root package.
ROOT_PKG_PATH = (PROJECT_PATH / "src" / "supa").resolve(strict=True)

# Relative path (to SuPA's root package) of the package that will contain the protobuf/gRPC generated code.
GEN_CODE_REL_PKG_PATH = Path("grpc_nsi")

# The absolute path of where we expect the protobuf/gRPC definitions to live.
PROTOS_PATH = (PROJECT_PATH / "protos").resolve(strict=True)


class GenCode(setuptools.Command):
    """Generate Python code from protobuf/gRPC definitions.

    This class, together with the `cmdclass` definition in the call to `setup()` defines a new command `gen_code`.
    When running::

        python setup.py gen_code

    it will generate Python code from the protobuf/gRPC definitions included in this project (see `PROTOS_PATH`).
    """

    user_options: List[Tuple[Optional[str], ...]] = []

    def initialize_options(self) -> None:  # noqa: D102
        pass

    def finalize_options(self) -> None:  # noqa: D102
        pass

    def run(self) -> None:  # noqa: D102
        try:
            # With help of PEP-518 and the `build-system` configuration in `pyproject.toml`, `pip install -e .` will
            # pre-install this for us before this code is run. Hence the import should not fail.
            import grpc_tools.protoc
        except ImportError as ie:
            # Though should it fail for some magical reason, it doesn't hurt to help the user with manual instructions.
            raise RuntimeError(
                "Before installing 'supa', run: pip install setuptools wheels grpcio-tools~=1.29 "
                "(Check exact version number in `setup.cfg`. Needs to be the same as that of `grpcio`)"
            ) from ie

        gen_code_path = ROOT_PKG_PATH / GEN_CODE_REL_PKG_PATH
        gen_code_path.mkdir(exist_ok=True)

        # Include common gRPC protobuf definitions
        proto_include = pkg_resources.resource_filename("grpc_tools", "_proto")

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


class InstallCommand(install):
    """Support Python code generation during package installation."""

    def run(self) -> None:  # noqa: D102
        self.run_command("gen_code")
        super().run()


class DevelopCommand(develop):
    """Support Python code generation during 'editable' package installation."""

    def run(self) -> None:  # noqa: D102
        self.run_command("gen_code")
        super().run()


class CleanCommand(clean):
    """Custom cleanup for generated code."""

    def run(self) -> None:  # noqa: D102
        gen_code_path = ROOT_PKG_PATH / GEN_CODE_REL_PKG_PATH
        if gen_code_path.exists():
            shutil.rmtree(gen_code_path)
        super().run()


# Most configuration is done in `setup.cfg`, but here we add a command and customize two existing commands to be able
# to generate Python code from protobuf/gRPC definitions during installation.
setuptools.setup(
    name="supa",
    cmdclass={"gen_code": GenCode, "install": InstallCommand, "develop": DevelopCommand, "clean": CleanCommand},
)
