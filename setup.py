"""Distutils/setuptools packaging information file."""
import shutil
from distutils.command.clean import clean
from pathlib import Path

import pkg_resources
import setuptools
from setuptools.command.develop import develop
from setuptools.command.install import install

# The absolute path where this project resides.
PROJECT_PATH = Path(__file__).resolve().parent

# The absolute path of SuPA's root package.
ROOT_PKG_PATH = (PROJECT_PATH / "src" / "supa").resolve(strict=True)

# Relative path (to SuPA's root package) of the package that will contain the protobuf/gRPC generated code.
GEN_CODE_REL_PKG_PATH = Path("grpc")

# The absolute path of where we expect the protobuf/gRPC definitions to live.
PROTOS_PATH = (PROJECT_PATH / "protos").resolve(strict=True)


class GenCode(setuptools.Command):
    """Generate Python code from protobuf/gRPC definitions.

    This class, together with the `cmdclass` definition in the call to `setup()` defines a new command `gen_code`.
    When running::

        python setup.py gen_code

    it will generate Python code from the protobuf/gRPC definitions included in this project (see `PROTOS_PATH`).
    """

    user_options = []

    def initialize_options(self):
        pass

    def finalize_options(self):
        pass

    def run(self):
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

        # The generated code should be part of a package
        (gen_code_path / "__init__.py").touch(mode=0o644, exist_ok=True)

        # Include common gRPC protobuf definitions
        proto_include = pkg_resources.resource_filename("grpc_tools", "_proto")

        proto_files = list(PROTOS_PATH.glob("*.proto"))
        if len(proto_files) == 0:
            raise RuntimeError(
                "Could not find any protobuf files in directory '{}'. Hence no Python code to generate.".format(
                    PROTOS_PATH
                )
            )
        # The protoc compiler (with gRPC plugin) seem to only accept one proto file at a time
        for pf in proto_files:
            exit_code = grpc_tools.protoc.main(
                [
                    "grpc_tools.protoc",
                    "--proto_path={}".format(proto_include),
                    "--proto_path={}".format(PROTOS_PATH),
                    "--python_out={}".format(gen_code_path),
                    "--grpc_python_out={}".format(gen_code_path),
                    pf.as_posix(),
                ]
            )
            if exit_code != 0:
                raise RuntimeError(
                    "Could not generate Python code from protobuf file '{}'. Exit code: {}".format(pf, exit_code)
                )


class InstallCommand(install):
    """Support Python code generation during package installation."""

    def run(self):
        self.run_command("gen_code")
        super().run()


class DevelopCommand(develop):
    """Support Python code generation during 'editable' package installation."""

    def run(self):
        self.run_command("gen_code")
        super().run()


class CleanCommand(clean):
    """Custom cleanup for generated code."""

    def run(self):
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
