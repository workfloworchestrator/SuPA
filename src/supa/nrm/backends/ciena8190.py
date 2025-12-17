# Contributed by Andrew Lytvynov (CANARIE Inc.), 2025
import logging
from typing import Any, Generator, Optional
from uuid import UUID, uuid4

import xmltodict
from ncclient import manager
from pydantic_settings import BaseSettings

from supa.connection.error import GenericRmError
from supa.job.shared import NsiException
from supa.nrm.backend import STP, BaseBackend
from supa.util.find import find_file

logging.getLogger("ncclient").setLevel(logging.WARNING)


class BackendSettings(BaseSettings):
    host: str = ""
    port: int = 0
    username: str = ""
    password: str = ""


class Ciena8190:
    """Ciena 8190 NETCONF XML templates"""

    CANDIDATE = "candidate"
    RUNNING = "running"
    CONFIG = """
      <config xmlns="urn:ietf:params:xml:ns:netconf:base:1.0">
        {config}
      </config>
    """

    # Classifiers
    GET_CLASSIFIERS = """
      <classifiers xmlns="urn:ciena:params:xml:ns:yang:ciena-pn::ciena-mef-classifier" />
    """
    CREATE_CLASSIFIER = """
      <classifiers xmlns="urn:ciena:params:xml:ns:yang:ciena-pn::ciena-mef-classifier">
        <classifier operation="{operation}">
          <name>{name}</name>
          <filter-entry>
            <filter-parameter>vtag-stack</filter-parameter>
            <vtags>
              <tag>1</tag>
              <vlan-id>{vlan}</vlan-id>
            </vtags>
          </filter-entry>
        </classifier>
      </classifiers>
    """
    DELETE_CLASSIFIER = """
      <classifiers xmlns="urn:ciena:params:xml:ns:yang:ciena-pn::ciena-mef-classifier">
        <classifier operation="delete">
          <name>{name}</name>
        </classifier>
      </classifiers>
    """

    # Flow Points
    GET_FLOW_POINTS = """
      <fps xmlns="urn:ciena:params:xml:ns:yang:ciena-pn:ciena-mef-fp" />
    """
    CREATE_FLOW_POINT = """
      <fps xmlns="urn:ciena:params:xml:ns:yang:ciena-pn:ciena-mef-fp">
        <fp operation="{operation}">
          <name>{name}</name>
          <admin-state>enabled</admin-state>
          <description>{description}</description>
          <fd-name>{fd}</fd-name>
          <logical-port>{port}</logical-port>
          <classifier-list>{classifier}</classifier-list>
          <stats-collection>on</stats-collection>
        </fp>
      </fps>
    """
    DELETE_FLOW_POINT = """
      <fps xmlns="urn:ciena:params:xml:ns:yang:ciena-pn:ciena-mef-fp">
        <fp operation="delete">
          <name>{name}</name>
        </fp>
      </fps>
    """
    DISABLE_FLOW_POINT = """
      <fps xmlns="urn:ciena:params:xml:ns:yang:ciena-pn:ciena-mef-fp">
        <fp operation="merge">
          <name>{name}</name>
          <admin-state>disabled</admin-state>
        </fp>
      </fps>
    """

    # Forwarding Domains
    GET_FORWARDING_DOMAINS = """
      <fds xmlns="urn:ciena:params:xml:ns:yang:ciena-pn:ciena-mef-fd" />
    """
    CREATE_FORWADING_DOMAIN = """
      <fds xmlns="urn:ciena:params:xml:ns:yang:ciena-pn:ciena-mef-fd">
        <fd operation="{operation}">
          <name>{name}</name>
          <description>{description}</description>
          <mode>vpls</mode>
          <mac-learning>enabled</mac-learning>
        </fd>
      </fds>
    """
    DELETE_FORWADING_DOMAIN = """
      <fds xmlns="urn:ciena:params:xml:ns:yang:ciena-pn:ciena-mef-fd">
        <fd operation="delete">
          <name>{name}</name>
        </fd>
      </fds>
    """

    @staticmethod
    def create_classifier(
        name: str,
        vlan: int,
        operation: str = "merge",
    ) -> str:
        """Create a classifier on the device

        Attributes:
            name: The name of the classifier
            vlan: The VLAN ID to match
            operation: The NETCONF operation to perform, default is 'merge'
        """
        return Ciena8190.CONFIG.format(
            config=Ciena8190.CREATE_CLASSIFIER.format(name=name, vlan=vlan, operation=operation)
        )

    @staticmethod
    def create_forwarding_domain(
        name: str,
        description: str = "",
        operation: str = "merge",
    ) -> str:
        """Create a forwarding domain on the device

        Attributes:
            name: The name of the forwarding domain,
            description: A description for the forwarding domain
            operation: The NETCONF operation to perform, default is 'merge'
        """
        return Ciena8190.CONFIG.format(
            config=Ciena8190.CREATE_FORWADING_DOMAIN.format(name=name, description=description, operation=operation)
        )

    @staticmethod
    def create_flow_point(
        name: str,
        fd: str,
        port: str,
        classifier: str,
        description: str = "",
        operation: str = "merge",
    ) -> str:
        """Create a flow point on the device

        Attributes:
            name: The name of the flow point
            fd: The name of the forwarding domain to associate with the flow point
            port: The logical port to associate with the flow point
            classifier: The name of the classifier to associate with the flow point
            description: A description for the flow point
            operation: The NETCONF operation to perform, default is 'merge'
        """
        return Ciena8190.CONFIG.format(
            config=Ciena8190.CREATE_FLOW_POINT.format(
                name=name,
                description=description,
                fd=fd,
                port=port,
                classifier=classifier,
                operation=operation,
            )
        )

    @staticmethod
    def delete_classifier(
        name: str,
    ) -> str:
        """Delete a classifier on the device

        Attributes:
            name: The name of the classifier
        """
        return Ciena8190.CONFIG.format(config=Ciena8190.DELETE_CLASSIFIER.format(name=name))

    @staticmethod
    def delete_forwarding_domain(
        name: str,
    ) -> str:
        """Delete a forwarding domain on the device

        Attributes:
            name: The name of the forwarding domain
        """
        return Ciena8190.CONFIG.format(config=Ciena8190.DELETE_FORWADING_DOMAIN.format(name=name))

    @staticmethod
    def delete_flow_point(
        name: str,
    ) -> str:
        """Delete a flow point on the device

        Attributes:
            name: The name of the flow point
        """
        return Ciena8190.CONFIG.format(config=Ciena8190.DELETE_FLOW_POINT.format(name=name))

    @staticmethod
    def disable_flow_point(
        name: str,
    ) -> str:
        """Disable a flow point on the device

        Attributes:
            name: The name of the flow point
        """
        return Ciena8190.CONFIG.format(config=Ciena8190.DISABLE_FLOW_POINT.format(name=name))


class Backend(BaseBackend):

    def _iter(self, element: list | dict) -> Generator:
        """Iterate over a list or a single element.

        Based on how xmltodict parses XML, YANG containers may be represented
        as a single element instead of a list. This helper function ensures
        consistent iteration over either a list or a single element within
        such containers.

        Args:
            element (list or dict): A list or a single element of a container.

        Yields:
            dict: A single element of the container.

        Doctest:
            >>> list(Backend._iter([1, 2, 3]))
            [1, 2, 3]
            >>> list(Backend._iter(1))
            [1]
        """
        if isinstance(element, list):
            for e in element:
                yield e
        else:
            yield element

    def __init__(self) -> None:
        super(Backend, self).__init__()
        self._settings = BackendSettings(_env_file=(env_file := find_file("ciena8190.env")))  # type: ignore[call-arg]
        self.log.info("Read backend properties", path=str(env_file))
        self._manager = None
        self._capabilities: list[str] = []
        self._is_candidate_flag: Optional[bool] = None

    def _get_ports(self) -> dict:
        """Get a mapping of ports to STP IDs and VLAN ranges

        Return Example:
            {
                'et-0/0/19': {
                    (1100, 4000): 'AMST1',
                },
                'et-0/0/13': {
                    (1100, 4000): 'NYCN1',
                },
            }
        """
        if not hasattr(self, "_ports"):
            self._ports: dict[str, dict[tuple[int, int], str]] = {}
            for stp in self.topology():
                if stp.port_id not in self._ports:
                    self._ports[stp.port_id] = {}
                for vlans in stp.vlans.split(","):
                    (start_vlan, end_vlan) = (
                        (int(vlans), int(vlans)) if "-" not in vlans else tuple(map(int, vlans.split("-")))
                    )
                    self._ports[stp.port_id][(start_vlan, end_vlan)] = stp.stp_id
        return self._ports

    def _get_stp_id(
        self,
        port_id: str,
        vlan: int,
    ) -> Any:
        """Get the STP ID for a given port and VLAN

        Example:
            >>> Backend._get_stp_id(port_id='et-0/0/19', vlan=1100)
            'AMST1'
        """
        ports = self._get_ports()
        if port_id not in self._get_ports():
            raise NsiException(GenericRmError, "Port {port} not found".format(port=port_id))
        for (start_vlan, end_vlan), stp_id in ports[port_id].items():
            if start_vlan <= vlan <= end_vlan:
                return stp_id
        raise NsiException(GenericRmError, "VLAN {vlan} not found on the port {port}".format(port=port_id, vlan=vlan))

    def _get_manager(self) -> manager.Manager:
        """Return an active NETCONF manager session"""
        if not self._manager:
            try:
                self._manager = manager.connect(
                    host=self._settings.host,
                    port=self._settings.port,
                    username=self._settings.username,
                    password=self._settings.password,
                    hostkey_verify=False,
                    timeout=5,
                    # Enables the use of an SSH agent to provide authentication credentials
                    # from memory.
                    allow_agent=False,
                    # Controls whether to search the filesystem for SSH private keys stored
                    # in the default directories (like ~/.ssh).
                    look_for_keys=False,
                )
            except Exception as e:
                self.log.warning("Failed to connect to device", reason=str(e))
                raise NsiException(GenericRmError, str(e)) from e
            self.log.info(
                "Connected to device",
                host=self._settings.host,
                port=self._settings.port,
                username=self._settings.username,
            )
        return self._manager

    def _get_capabilities(self) -> list[Any]:
        """Get the device capabilities"""
        if not self._capabilities:
            self._capabilities = self._get_manager().server_capabilities
        return self._capabilities

    def _is_candidate(self) -> bool:
        """Check whether candidate datastore is activated"""
        _str = "urn:ietf:params:netconf:capability:candidate:1.0"
        if self._is_candidate_flag is None:
            self._is_candidate_flag = _str in self._get_capabilities()
        return self._is_candidate_flag

    def _get_target(self) -> str:
        """Return the appropriate target datastore"""
        return Ciena8190.CANDIDATE if self._is_candidate() else Ciena8190.RUNNING

    def _create_classifier(
        self,
        name: str,
        vlan: int,
    ) -> None:
        """Create a classifier on the device"""
        self.log.info("Creating source classifier", name=name, vlan=vlan)
        try:
            self._get_manager().edit_config(
                target=self._get_target(),
                config=Ciena8190.create_classifier(name=name, vlan=vlan),
            )
        except Exception as e:
            self.log.warning("Failed to create source classifier", reason=str(e))
            self._discard()
            raise NsiException(GenericRmError, "Failed to create source classifier") from e
        self.log.info("Source classifier created successfully", name=name, vlan=vlan)

    def _create_forwarding_domain(
        self,
        name: str,
        description: str = "",
    ) -> None:
        """Create a forwarding domain on the device"""
        self.log.info("Creating forwarding domain", name=name)
        try:
            self._get_manager().edit_config(
                target=self._get_target(),
                config=Ciena8190.create_forwarding_domain(name=name, description=description),
            )
        except Exception as e:
            self.log.warning("Failed to create forwarding domain", reason=str(e))
            self._discard()
            raise NsiException(GenericRmError, "Failed to create forwarding domain") from e
        self.log.info("Forwarding domain created successfully", name=name)

    def _create_flow_point(
        self,
        name: str,
        fd: str,
        port: str,
        classifier: str,
        description: str = "",
    ) -> None:
        """Create a flow point on the device"""
        self.log.info("Creating flow point", name=name, fd=fd, port=port, classifier=classifier)
        try:
            self._get_manager().edit_config(
                target=self._get_target(),
                config=Ciena8190.create_flow_point(
                    name=name,
                    description=description,
                    fd=fd,
                    port=port,
                    classifier=classifier,
                ),
            )
        except Exception as e:
            self.log.warning("Failed to create flow point", reason=str(e))
            self._discard()
            raise NsiException(GenericRmError, "Failed to create flow point") from e
        self.log.info(
            "Flow point created successfully",
            name=name,
            fd=fd,
            port=port,
            classifier=classifier,
        )

    def _validate(self) -> None:
        """Validate the candidate configuration on the device"""
        self.log.info("Validating configuration")
        try:
            self._get_manager().validate(source=self._get_target())
        except Exception as e:
            self.log.warning("Failed to validate the configuration", reason=str(e))
            self._discard()
            raise NsiException(GenericRmError, "Failed to validate the configuration") from e
        self.log.info("Configuration validated successfully")

    def _discard(self) -> None:
        """Discard the candidate configuration on the device"""
        if self._is_candidate():
            self.log.info("Discarding configuration")
            try:
                self._get_manager().discard_changes()
            except Exception as e:
                self.log.warning("Failed to discard the configuration", reason=str(e))
                raise NsiException(GenericRmError, "Failed to discard the configuration") from e
            self.log.info("Configuration discarded successfully")

    def _commit(self) -> None:
        """Commit the candidate configuration on the device"""
        if self._is_candidate():
            self.log.info("Committing configuration")
            try:
                self._get_manager().commit()
            except Exception as e:
                self.log.warning("Failed to commit the configuration", reason=str(e))
                self._discard()
                raise NsiException(GenericRmError, "Failed to commit the configuration") from e
            self.log.info("Configuration committed successfully")

    def _parse_classifiers(self) -> dict:
        """Parse existing classifiers on the device

        Return Example:
          "CL-opennsa-20-111": {
            "name": "CL-opennsa-20-111",
            "vlan": 111
          }
        """
        self.log.info("Parsing classifiers")
        try:
            response = self._get_manager().get(("subtree", Ciena8190.GET_CLASSIFIERS))
            config = xmltodict.parse(response.data_xml)

            classifiers = {}
            _classifiers = self._iter(config.get("data", {}).get("classifiers", {}).get("classifier", []))
            for classifier in _classifiers:
                name = classifier["name"]
                try:
                    vlan = int(classifier.get("filter-entry", {}).get("vtags", {}).get("vlan-id", None))
                    classifiers[name] = {
                        "name": name,
                        "vlan": vlan,
                    }
                except Exception:
                    self.log.warning("Skipping classifier {name} due to missing VLAN".format(name=name))
        except Exception as e:
            self.log.warning("Failed to parse classifiers", reason=str(e))
            raise NsiException(GenericRmError, "Failed to parse classifiers") from e
        self.log.info("Classifiers parsed successfully", count=len(classifiers))
        return classifiers

    def _parse_forwarding_domains(self) -> dict:
        """Parse existing forwarding domains on the device

        Return Example:
          "FD-opennsa-19-20-111-111": {
            "name": "FD-opennsa-19-20-111-111"
          }
        """
        self.log.info("Parsing forwarding domains")
        try:
            response = self._get_manager().get(("subtree", Ciena8190.GET_FORWARDING_DOMAINS))
            config = xmltodict.parse(response.data_xml)

            fds = {}
            _fds = self._iter(config.get("data", {}).get("fds", {}).get("fd", []))
            for fd in _fds:
                name = fd["name"]
                fds[name] = {
                    "name": name,
                }
        except Exception as e:
            self.log.warning("Failed to parse forwarding domains", reason=str(e))
            raise NsiException(GenericRmError, "Failed to parse forwarding domains") from e
        self.log.info("Forwarding domains parsed successfully", count=len(fds))
        return fds

    def _parse_flow_points(self) -> dict:
        """Parse existing flow points on the device

        Return Example:
          "FP-opennsa-19-111": {
            "name": "FP-opennsa-19-111",
            "port": "19",
            "fd": "FD-opennsa-19-20-111-111",
            "classifiers": [
              "CL-opennsa-19-111"
            ]
          }
        """
        self.log.info("Parsing flow points")
        try:
            response = self._get_manager().get(("subtree", Ciena8190.GET_FLOW_POINTS))
            config = xmltodict.parse(response.data_xml)

            fps = {}
            _fps = self._iter(config.get("data", {}).get("fps", {}).get("fp", []))
            for fp in _fps:
                name = fp["name"]
                admin_state = True if fp.get("admin-state", "enabled") == "enabled" else False
                port = fp["logical-port"]
                fd = fp["fd-name"]
                classifiers = list(self._iter(fp.get("classifier-list", [])))
                fps[name] = {
                    "name": name,
                    "admin_state": admin_state,
                    "port": port,
                    "fd": fd,
                    "classifiers": classifiers,
                }
        except Exception as e:
            self.log.warning("Failed to parse flow points", reason=str(e))
            raise NsiException(GenericRmError, "Failed to parse flow points") from e
        self.log.info("Flow points parsed successfully", count=len(fps))
        return fps

    def _delete_classifier(self, name: str) -> None:
        """Delete a classifier on the device"""
        self.log.info("Deleting classifier", name=name)
        try:
            self._get_manager().edit_config(target=self._get_target(), config=Ciena8190.delete_classifier(name=name))
        except Exception as e:
            self.log.warning("Failed to delete classifier", reason=str(e))
            self._discard()
            raise NsiException(GenericRmError, "Failed to delete classifier") from e
        self.log.info("Classifier deleted successfully", name=name)

    def _delete_forwarding_domain(self, name: str) -> None:
        """Delete a forwarding domain on the device"""
        self.log.info("Deleting forwarding domain", name=name)
        try:
            self._get_manager().edit_config(
                target=self._get_target(),
                config=Ciena8190.delete_forwarding_domain(name=name),
            )
        except Exception as e:
            self.log.warning("Failed to delete forwarding domain", reason=str(e))
            self._discard()
            raise NsiException(GenericRmError, "Failed to delete forwarding domain") from e
        self.log.info("Forwarding domain deleted successfully", name=name)

    def _delete_flow_point(self, name: str) -> None:
        """Delete a flow point on the device"""
        self.log.info("Deleting flow point", name=name)
        try:
            self._get_manager().edit_config(target=self._get_target(), config=Ciena8190.delete_flow_point(name=name))
        except Exception as e:
            self.log.warning("Failed to delete flow point", reason=str(e))
            self._discard()
            raise NsiException(GenericRmError, "Failed to delete flow point") from e
        self.log.info("Flow point deleted successfully", name=name)

    def _disable_flow_point(self, name: str) -> None:
        """Disable a flow point on the device"""
        self.log.info("Disabling flow point", name=name)
        try:
            self._get_manager().edit_config(
                target=self._get_target(),
                config=Ciena8190.disable_flow_point(name=name),
            )
        except Exception as e:
            self.log.warning("Failed to disable flow point", reason=str(e))
            self._discard()
            raise NsiException(GenericRmError, "Failed to disable flow point") from e
        self.log.info("Flow point disabled successfully", name=name)

    def _get_lookup(self) -> dict:
        """Get lookup table of existing resources on the device

        Return Example:
          {
            ('19', 111, '20', 111): {
              'fd': 'FD-opennsa-19-20-111-111',
              'flow_points': {'FP-opennsa-19-111', 'FP-opennsa-20-111'},
              'classifiers': {'CL-opennsa-19-111', 'CL-opennsa-20-111'}
            },
            ('20', 111, '19', 111): {
              'fd': 'FD-opennsa-19-20-111-111',
              'flow_points': {'FP-opennsa-19-111', 'FP-opennsa-20-111'},
              'classifiers': {'CL-opennsa-19-111', 'CL-opennsa-20-111'}
            }
          }
        """
        if not hasattr(self, "_lookup"):
            classifiers = self._parse_classifiers()
            fps = self._parse_flow_points()

            # NOTE: No current support for multiple classifiers on a flow point
            if any([len(v["classifiers"]) != 1 for _, v in fps.items()]):
                raise NsiException(
                    GenericRmError,
                    "Multiple classifiers configured on the single flow point: {fp}".format(
                        fp=next(fd for fd, v in fps.items() if len(v["classifiers"]) != 1)
                    ),
                )

            fds = {
                fd_name: {
                    **fd,
                    "flow_points": {fp_name: fp for fp_name, fp in fps.items() if fp["fd"] == fd_name},
                }
                for fd_name, fd in self._parse_forwarding_domains().items()
            }

            # Filter out only forwarding domains that have two flow points
            fds = {fd_name: fd for fd_name, fd in fds.items() if len(fd["flow_points"]) == 2}

            # NOTE: There is option to filter classifiers, flow points and
            # forwarding domains based on their name.

            """
            Example of fds key/value after parsing:
              "FD-opennsa-19-20-111-111": {
                "name": "FD-opennsa-19-20-111-111",
                "flow_points": {
                  "FP-opennsa-19-111": {
                    "name": "FP-opennsa-19-111",
                    "admin_state": false,
                    "port": "19",
                    "fd": "FD-opennsa-19-20-111-111",
                    "classifiers": [
                      "CL-opennsa-19-111"
                    ]
                  },
                  "FP-opennsa-20-111": {
                    "name": "FP-opennsa-20-111",
                    "admin_state": true,
                    "port": "20",
                    "fd": "FD-opennsa-19-20-111-111",
                    "classifiers": [
                      "CL-opennsa-20-111"
                    ]
                  }
                }
              }
            """

            # Forming lookup table
            lookup = {}
            for _, fd in fds.items():
                _fps = list(fd["flow_points"].values())
                port1 = _fps[0]["port"]
                port2 = _fps[1]["port"]
                vlan1 = classifiers[_fps[0]["classifiers"][0]]["vlan"]
                vlan2 = classifiers[_fps[1]["classifiers"][0]]["vlan"]
                values = {
                    "fd": fd["name"],
                    "flow_points": set(fd["flow_points"].keys()),
                    "classifiers": set([e for fp in fd["flow_points"].values() for e in fp["classifiers"]]),
                }
                lookup[(port1, vlan1, port2, vlan2)] = values
                lookup[(port2, vlan2, port1, vlan1)] = values

            self._lookup = lookup
        return self._lookup

    def activate(
        self,
        connection_id: UUID,
        bandwidth: int,
        src_port_id: str,
        src_vlan: int,
        dst_port_id: str,
        dst_vlan: int,
        circuit_id: str,
    ) -> str:
        """Activate resources on the device"""
        if not src_vlan == dst_vlan:
            raise NsiException(GenericRmError, "VLANs must match")

        _src_stp = self._get_stp_id(src_port_id, src_vlan)
        _dst_stp = self._get_stp_id(dst_port_id, dst_vlan)
        forwarding_domain = "opennsa-{src_stp}-{dst_stp}-{src_vlan}-{dst_vlan}".format(
            src_stp=_src_stp, dst_stp=_dst_stp, src_vlan=src_vlan, dst_vlan=dst_vlan
        )
        src_classifier = "opennsa-{stp}-{vlan}".format(stp=_src_stp, vlan=src_vlan)
        dst_classifier = "opennsa-{stp}-{vlan}".format(stp=_dst_stp, vlan=dst_vlan)
        src_flow_point = "opennsa-{stp}-{vlan}".format(stp=_src_stp, vlan=src_vlan)
        dst_flow_point = "opennsa-{stp}-{vlan}".format(stp=_dst_stp, vlan=dst_vlan)

        # Create classifiers
        self._create_classifier(name=src_classifier, vlan=src_vlan)
        self._create_classifier(name=dst_classifier, vlan=dst_vlan)

        # Create forwarding domain
        self._create_forwarding_domain(name=forwarding_domain, description=forwarding_domain)

        # Create flow points
        self._create_flow_point(
            name=src_flow_point,
            fd=forwarding_domain,
            port=src_port_id,
            classifier=src_classifier,
            description=src_flow_point,
        )
        self._create_flow_point(
            name=dst_flow_point,
            fd=forwarding_domain,
            port=dst_port_id,
            classifier=dst_classifier,
            description=dst_flow_point,
        )

        # Validate configuration
        self._validate()

        # Commit configuration
        self._commit()

        # Report success
        circuit_id = str(uuid4())
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
    ) -> None:
        """Deactivate resources on the device, instead of deleting"""
        self.log.info(
            "Lookup for the link to deactivate",
            src_port_id=src_port_id,
            dst_port_id=dst_port_id,
            src_vlan=src_vlan,
            dst_vlan=dst_vlan,
        )
        try:
            circuit = self._get_lookup()[(src_port_id, src_vlan, dst_port_id, dst_vlan)]
        except KeyError:
            self.log.warning(
                "No such circuit exists",
                src_port_id=src_port_id,
                dst_port_id=dst_port_id,
                src_vlan=src_vlan,
                dst_vlan=dst_vlan,
            )
            raise NsiException(GenericRmError, "No such circuit exists") from None

        # Disable flow points
        for fp in circuit["flow_points"]:
            self._disable_flow_point(name=fp)

        # Validate configuration
        self._validate()

        # Commit configuration
        self._commit()

        self.log.info(
            "Link down",
            src_port_id=src_port_id,
            dst_port_id=dst_port_id,
            src_vlan=src_vlan,
            dst_vlan=dst_vlan,
            circuit_id=circuit_id,
        )
        # Returning None keeps the circuit ID as is
        return None

    def terminate(
        self,
        connection_id: UUID,
        bandwidth: int,
        src_port_id: str,
        src_vlan: int,
        dst_port_id: str,
        dst_vlan: int,
        circuit_id: str,
    ) -> None:
        """Terminate resources"""
        self.log.info(
            "Lookup for the link to delete",
            src_port_id=src_port_id,
            dst_port_id=dst_port_id,
            src_vlan=src_vlan,
            dst_vlan=dst_vlan,
        )
        try:
            circuit = self._get_lookup()[(src_port_id, src_vlan, dst_port_id, dst_vlan)]
        except KeyError:
            self.log.warning(
                "No such circuit exists",
                src_port_id=src_port_id,
                dst_port_id=dst_port_id,
                src_vlan=src_vlan,
                dst_vlan=dst_vlan,
            )
            raise NsiException(GenericRmError, "No such circuit exists") from None
        self.log.info(
            "Link found",
            src_port_id=src_port_id,
            dst_port_id=dst_port_id,
            src_vlan=src_vlan,
            dst_vlan=dst_vlan,
            circuit=circuit,
        )

        # NOTE: The order of deletion is important for Ciena 8190 devices
        # especially when using writable running datastore.

        # Delete flow points
        for fp in circuit["flow_points"]:
            self._delete_flow_point(name=fp)

        # Delete forwarding domain
        self._delete_forwarding_domain(name=circuit["fd"])

        # Delete classifiers
        for classifier in circuit["classifiers"]:
            self._delete_classifier(name=classifier)

        # Validate configuration
        self._validate()

        # Commit configuration
        self._commit()

        self.log.info(
            "Link Deleted",
            src_port_id=src_port_id,
            dst_port_id=dst_port_id,
            src_vlan=src_vlan,
            dst_vlan=dst_vlan,
            circuit_id=circuit_id,
        )


if __name__ == "__main__":
    import logging

    def __init__(self: Any) -> None:
        # Mock BaseBackend
        self.topology = lambda: [
            STP(
                stp_id="AMST1",
                port_id="19",
                vlans="1100-4000",
                description=None,
                is_alias_in="test.com:2025:production#out",
                is_alias_out="test.com:2025:production#in",
                bandwidth=800000,
                enabled=True,
                topology="topology",
            ),
            STP(
                stp_id="NYCN1",
                port_id="13",
                vlans="1100-4000",
                description=None,
                is_alias_in=None,
                is_alias_out=None,
                bandwidth=800000,
                enabled=True,
                topology="topology",
            ),
        ]
        self._str = lambda *args, **kwargs: " ".join(
            [str(a) for a in args] + list({'%s="%s"' % (k, v) for k, v in kwargs.items()})
        )
        self.log = type(
            "Object",
            (),
            {
                "info": lambda *args, **kwargs: logging.info(self._str(*args, **kwargs)),
                "debug": lambda *args, **kwargs: logging.debug(self._str(*args, **kwargs)),
                "warning": lambda *args, **kwargs: logging.warning(self._str(*args, **kwargs)),
            },
        )()
        #
        # Original __init__
        self._settings = BackendSettings(_env_file=(env_file := find_file("ciena8190.env")))  # type: ignore[call-arg]
        self.log.info("Read backend properties", path=str(env_file))
        self._manager = None
        self._capabilities = None
        self._is_candidate_flag = None

    Backend.__init__ = __init__  # type: ignore[method-assign]
    backend = Backend()

    input("Press Enter to continue to activate...")
    backend.activate(
        connection_id=UUID(int=0),
        bandwidth=999,
        src_port_id="19",
        src_vlan=1111,
        dst_port_id="13",
        dst_vlan=1111,
        circuit_id="any",
    )
    input("Press Enter to continue to deactivate...")
    backend.deactivate(
        connection_id=UUID(int=0),
        bandwidth=999,
        src_port_id="19",
        src_vlan=1111,
        dst_port_id="13",
        dst_vlan=1111,
        circuit_id="any",
    )
    input("Press Enter to continue to terminate...")
    backend.terminate(
        connection_id=UUID(int=0),
        bandwidth=999,
        src_port_id="19",
        src_vlan=1111,
        dst_port_id="13",
        dst_vlan=1111,
        circuit_id="any",
    )
