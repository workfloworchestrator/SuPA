"""Distutils/setuptools packaging information file."""
from pathlib import Path

import pkg_resources
import setuptools
from setuptools.command.develop import develop
from setuptools.command.install import install


class GenCode(setuptools.Command):
    """Generate Python code from protobuf/gRPC definitions.

    This class, together with the `cmdclass` definition in the call to `setup()` defines a new command `gen_code`.
    When running::

        python setup.py gen_code

    it will generate Python code from the protobuf/gRPC definitions included in this project (see `PROTOS_PATH`).
    """

    # Paths are hard coded as they are specific to this project anyway.
    PY_OUT_PATH = Path("src/supa").resolve(strict=True) / "grpc"
    PY_OUT_PATH.mkdir(exist_ok=True)
    PROTOS_PATH = Path("protos").resolve(strict=True)

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

        # Include common gRPC protobuf definitions
        proto_include = pkg_resources.resource_filename("grpc_tools", "_proto")

        # The protoc compiler (with gRPC plugin) seem to only accept one proto file at a time
        for proto_file in GenCode.PROTOS_PATH.glob("*.proto"):
            exit_code = grpc_tools.protoc.main(
                [
                    "grpc_tools.protoc",
                    "--proto_path={}".format(proto_include),
                    "--proto_path={}".format(GenCode.PROTOS_PATH),
                    "--python_out={}".format(GenCode.PY_OUT_PATH),
                    "--grpc_python_out={}".format(GenCode.PY_OUT_PATH),
                    proto_file.as_posix(),
                ]
            )
            if exit_code != 0:
                raise RuntimeError(
                    "Could not generate Python code from protobuf file '{}'. Exit code: {}".format(
                        proto_file, exit_code
                    )
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


# Most configuration is done in `setup.cfg`, but here we add a command and customize two existing commands to be able
# to generate Python code from protobuf/gRPC definitions during installation.
setuptools.setup(name="supa", cmdclass={"gen_code": GenCode, "install": InstallCommand, "develop": DevelopCommand})
