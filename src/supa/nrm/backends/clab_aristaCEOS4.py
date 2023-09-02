#  Copyright 2023 ESnet / UCSD / SURF.
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
"""
Arista cEOS 4.x Backend for ContainerLab simulation.
Copied from paristaEOS4.py and adapted for Arista cEOS4.

Swith command prompt starts with ceos2# and config mode is ceos2(config)#

Configuration:
You need to first enable the switch cli for specified privilege commands level (Not shown in paristaEOS4.py).
ceos2>enable

To setup a VLAN connection:
// in sw cli mode on login
ceos2# configure
// config for source interface
ceos2(config)#vlan {$vlan}
ceos2(config)#exit
ceos2(config)#interface {$src_interface}
ceos2(config-if-{$et?})#switchport mode trunk
ceos2(config-if-{$et?})#switchport trunk allowed vlan add {$vlan}
ceos2(config-if-{$et?})#exit
// redo config for destination interface
ceos2(config)# interface {$dst_interface}
ceos2(config-if-{$et?})#switchport mode trunk
ceos2(config-if-{$et?})#switchport trunk allowed vlan add {$vlan}
ceos2(config-if-{$et?})#exit
// Saving config
ceos2#write

teardown:
// in sw cli mode on login
ceos2# configure
// rm vlan for source interface
ceos2(config)#interface {$src_interface}
ceos2(config-if-{$et?})#switchport trunk allowed vlan remove {$vlan}
ceos2(config-if-{$et?})#exit
// rm vlan for destination interface
ceos2(config)#interface {$dst_interface}
ceos2(config-if-{$et?})#switchport trunk allowed vlan remove {$vlan}
ceos2(config-if-{$et?})#exit
// Saving config
ceos2#write

// no use
# ceos2(config)#no vlan {$vlan}
# ceos2#copy running-config startup-config

"""
import os
from typing import List, Optional
from uuid import UUID, uuid4

import paramiko
from pydantic import BaseSettings

from supa.connection.error import GenericRmError
from supa.job.shared import NsiException
from supa.nrm.backend import BaseBackend
from supa.util.find import find_file


class BackendSettings(BaseSettings):
    """Backend settings with default values."""

    ssh_hostname: str = "localhost"
    ssh_port: int = 22
    ssh_host_fingerprint: str = ""
    ssh_username: str = ""
    ssh_password: str = ""
    ssh_private_key_path: str = ""
    ssh_public_key_path: str = ""

    cli_prompt: str = ""
    cli_needs_enable: bool = True

# parametrized commands
COMMAND_ENABLE = b"enable"
COMMAND_CONFIGURE = b"configure"
COMMAND_CREATE_VLAN = b"vlan %i"
COMMAND_DELETE_VLAN = b"no vlan %i"
COMMAND_INTERFACE = b"interface %s"
COMMAND_MODE_ACCESS = b"swi mode access"
COMMAND_MODE_TRUNK = b"swi mode trunk"
COMMAND_ACCESS_VLAN = b"swi access vlan %i"
COMMAND_TRUNK_ADD_VLAN = b"swi trunk allowed vlan add %i"
COMMAND_TRUNK_REM_VLAN = b"swi trunk allowed vlan remove %i"
COMMAND_EXIT = b"exit"
# COMMAND_COMMIT = 'copy running-config startup-config'
COMMAND_COMMIT = b"write"
COMMAND_NO_SHUTDOWN = b"no shutdown"


def _create_configure_commands(source_port: str, dest_port: str, vlan: int) -> List[bytes]:
    createvlan = COMMAND_CREATE_VLAN % vlan
    intsrc = COMMAND_INTERFACE % source_port.encode("utf-8")
    intdst = COMMAND_INTERFACE % dest_port.encode("utf-8")
    modetrunk = COMMAND_MODE_TRUNK
    addvlan = COMMAND_TRUNK_ADD_VLAN % vlan
    cmdexit = COMMAND_EXIT
    commands = [createvlan, cmdexit, intsrc, modetrunk, addvlan, cmdexit, intdst, modetrunk, addvlan, cmdexit]
    return commands


def _create_delete_commands(source_port: str, dest_port: str, vlan: int) -> List[bytes]:
    intsrc = COMMAND_INTERFACE % source_port.encode("utf-8")
    intdst = COMMAND_INTERFACE % dest_port.encode("utf-8")
    remvlan = COMMAND_TRUNK_REM_VLAN % vlan
    cmdexit = COMMAND_EXIT
    # deletevlan = COMMAND_DELETE_VLAN % vlan
    commands = [intsrc, remvlan, cmdexit, intdst, remvlan, cmdexit]  # , deletevlan]
    return commands


class Backend(BaseBackend):
    """Arista cEOS4 backend interface."""

    def __init__(self) -> None:
        """Load properties from 'clab_aristaCEOS4.env'."""
        super(Backend, self).__init__()
        # self.backend_settings = BackendSettings(_env_file=(env_file := find_file("clab_aristaCEOS4.env")))
        self.backend_settings = BackendSettings(_env_file=(env_file := find_file(os.path.basename(__file__).split('.')[0] + ".env")))
        self.log.info("Read backend properties", path=str(env_file))

    def _get_ssh_shell(self) -> None:
        self.sshclient = paramiko.SSHClient()
        self.sshclient.load_system_host_keys()
        self.sshclient.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        privkey = None

        try:
            if self.backend_settings.ssh_private_key_path:  # self.public_key_path
                if os.path.exists(
                    self.backend_settings.ssh_private_key_path
                ):  # and os.path.exists(self.public_key_path):
                    privkey = paramiko.RSAKey.from_private_key_file(self.backend_settings.ssh_private_key_path)

                elif os.path.exists(os.path.expanduser(self.backend_settings.ssh_private_key_path)):
                    privkey = paramiko.RSAKey.from_private_key_file(
                        os.path.expanduser(self.backend_settings.ssh_private_key_path)
                    )

                else:
                    reason = "Incorrect private key path or file does not exist"
                    self.log.warning("failed to initialise SSH client", reason=reason)
                    raise NsiException(GenericRmError, reason)

            if privkey:
                self.sshclient.connect(
                    hostname=self.backend_settings.ssh_hostname,
                    port=self.backend_settings.ssh_port,
                    username=self.backend_settings.ssh_username,
                    pkey=privkey,
                )

            elif self.backend_settings.ssh_password:
                # go with username/pass
                self.sshclient.connect(
                    hostname=self.backend_settings.ssh_hostname,
                    port=self.backend_settings.ssh_port,
                    username=self.backend_settings.ssh_username,
                    password=self.backend_settings.ssh_password,
                )
            else:
                raise AssertionError("No keys or password supplied")

        except Exception as exception:
            self.log.warning("SSH client connect failure", reason=str(exception))
            raise NsiException(GenericRmError, str(exception)) from exception

        transport = self.sshclient.get_transport()
        transport.set_keepalive(30)  # type: ignore[union-attr]
        self.channel = self.sshclient.invoke_shell()
        self.channel.settimeout(30)

    def _close_ssh_shell(self) -> None:
        self.channel.close()
        self.sshclient.close()

    def _send_commands(self, commands: List[bytes]) -> None:
        line = b""
        line_termination = b"\r"  # line termination
        self._get_ssh_shell()

        self.log.debug("_send_commands() function with cli list: %r" % commands)

        try:
            self.log.debug("Send command start")

            if self.backend_settings.cli_needs_enable:
                while not line.decode("utf-8").endswith(self.backend_settings.cli_prompt + ">"):
                    resp = self.channel.recv(999)
                    line += resp
                    self.log.debug(resp)
                line = b""
                
                # Enable Privileged Mode
                self.log.debug("Enable Privileged Mode")
                self.channel.send(COMMAND_ENABLE + line_termination)

            while not line.decode("utf-8").endswith(self.backend_settings.cli_prompt + "#"):
                resp = self.channel.recv(999)
                line += resp
                self.log.debug(resp)
            line = b""

            self.log.debug("Starting Config")
            self.channel.send(COMMAND_CONFIGURE + line_termination)
            while not line.decode("utf-8").endswith(self.backend_settings.cli_prompt + "(config)#"):
                resp = self.channel.recv(999)
                line += resp
                self.log.debug(resp)
            line = b""

            self.log.debug("Entered configure mode")
            for cmd in commands:
                self.log.debug("CMD> %r" % cmd)
                self.channel.send(cmd + line_termination)
                while not line.decode("utf-8").endswith(")#"):
                    resp = self.channel.recv(999)
                    line += resp
                    self.log.debug(resp)

                # self.log.debug(line)
                line = b""

            self.log.debug("Exiting configure mode")
            self.channel.send(COMMAND_EXIT + line_termination)
            while not line.decode("utf-8").endswith(self.backend_settings.cli_prompt + "#"):
                resp = self.channel.recv(999)
                line += resp
                self.log.debug(resp)

            line = b""
            self.log.debug("Exited configure mode; saving config")
            self.channel.send(COMMAND_COMMIT + line_termination)
            while not line.decode("utf-8").endswith(self.backend_settings.cli_prompt + "#"):
                resp = self.channel.recv(999)
                line += resp
                self.log.debug(resp)

        except Exception as exception:
            self._close_ssh_shell()
            self.log.warning("Error sending commands")
            raise NsiException(GenericRmError, "Error sending commands") from exception

        self._close_ssh_shell()
        self.log.debug("Commands successfully committed")

    def activate(
        self,
        connection_id: UUID,
        bandwidth: int,
        src_port_id: str,
        src_vlan: int,
        dst_port_id: str,
        dst_vlan: int,
        circuit_id: str,
    ) -> Optional[str]:
        """Activate resources."""
        if not src_vlan == dst_vlan:
            raise NsiException(GenericRmError, "VLANs must match")
        self._send_commands(_create_configure_commands(src_port_id, dst_port_id, dst_vlan))
        circuit_id = uuid4().urn  # dummy circuit id
        self.log.info(
            "Link up",
            src_port_id=src_port_id,
            dst_port_id=dst_port_id,
            src_vlan=src_vlan,
            dst_vlan=dst_vlan,
            circuit_id=circuit_id,
        )
        return circuit_id

    def deactivate(
        self,
        connection_id: UUID,
        bandwidth: int,
        src_port_id: str,
        src_vlan: int,
        dst_port_id: str,
        dst_vlan: int,
        circuit_id: str,
    ) -> Optional[str]:
        """Deactivate resources."""
        self._send_commands(_create_delete_commands(src_port_id, dst_port_id, dst_vlan))
        self.log.info(
            "Link down",
            src_port_id=src_port_id,
            dst_port_id=dst_port_id,
            src_vlan=src_vlan,
            dst_vlan=dst_vlan,
            circuit_id=circuit_id,
        )
        return None
