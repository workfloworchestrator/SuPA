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
"""Generate a NSI topology document.

Example topology document:

TODO include example topoloty document
"""
from datetime import timedelta
from typing import Union
from uuid import UUID

import cherrypy
import structlog
from lxml.etree import Element, QName, SubElement, tostring  # noqa: S410

from supa import settings
from supa.db.model import Port
from supa.nrm.backend import get_topology
from supa.util.timestamp import current_timestamp

log = structlog.get_logger(__name__)


def refresh_topology() -> None:
    """Refresh list of STP's in the database with topology from NRM, skip if configured for manual topology."""
    if settings.manual_topology:
        log.debug("skipping topology refresh", manual_topology=settings.manual_topology)
        return

    from supa.db.session import db_session

    stps = get_topology()
    stp_names = [stp.name for stp in stps]
    with db_session() as session:
        for stp in stps:
            if stp.topology != settings.network_type:
                log.debug("skip STP with unknown topology", name=stp.name, topology=stp.topology)
            else:
                port = session.query(Port).filter(Port.name == stp.name).one_or_none()
                if port:
                    log.debug("update existing STP", name=stp.name, topology=stp.topology)
                    port.port_id = UUID(stp.port_id)
                    port.vlans = stp.vlans
                    port.description = stp.description
                    port.is_alias_in = stp.is_alias_in
                    port.is_alias_out = stp.is_alias_out
                    port.bandwidth = stp.bandwidth
                    port.enabled = stp.expose_in_topology
                else:
                    log.info("add new STP", name=stp.name, topology=stp.topology)
                    session.add(
                        Port(
                            name=stp.name,
                            port_id=UUID(stp.port_id),
                            vlans=stp.vlans,
                            description=stp.description,
                            is_alias_in=stp.is_alias_in,
                            is_alias_out=stp.is_alias_out,
                            bandwidth=stp.bandwidth,
                            enabled=stp.expose_in_topology,
                        )
                    )
                for port in session.query(Port):
                    if port.name not in stp_names:
                        log.info("disable vanished STP", name=port.name, topology=stp.topology)
                        port.enabled = False


"""Namespace map for topology document."""
nsmap = {
    "topo": "http://schemas.ogf.org/nml/2013/05/base#",
    "sd": "http://schemas.ogf.org/nsi/2013/12/services/definition",
}


class Topology(object):
    """A cherryPy application to generate a NSI topology document."""

    @cherrypy.expose  # type: ignore[misc]
    def topology(self) -> Union[str, bytes]:
        """Cherrypy URL that returns the generated NSI topology document."""
        refresh_topology()
        network_id = f"urn:ogf:network:{settings.domain}:{settings.network_type}"
        now = current_timestamp()

        from supa.db.session import db_session

        with db_session() as session:
            ports = session.query(Port)

            topology = Element(QName(nsmap["topo"], "Topology"), nsmap=nsmap)
            topology.set("id", network_id)
            topology.set("version", now.isoformat(timespec="seconds"))
            name = SubElement(topology, "name")
            name.text = settings.topology_name
            lifetime = SubElement(topology, "Lifetime")
            lifetime_start = SubElement(lifetime, "start")
            lifetime_start.text = now.isoformat(timespec="seconds")
            lifetime_end = SubElement(lifetime, "end")
            lifetime_end.text = (now + timedelta(weeks=1)).isoformat(timespec="seconds")
            service_definition = SubElement(topology, QName(nsmap["sd"], "serviceDefinition"))
            service_definition.set("id", f"{network_id}:sd:EVTS.A-GOLE")
            service_definition_name = SubElement(service_definition, "name")
            service_definition_name.text = "GLIF Automated GOLE Ethernet VLAN Transfer Service"
            service_definition_service_type = SubElement(service_definition, "serviceType")
            service_definition_service_type.text = "http://services.ogf.org/nsi/2013/12/descriptions/EVTS.A-GOLE"
            relation = SubElement(topology, "Relation")
            relation.set("type", "http://schemas.ogf.org/nml/2013/05/base#hasService")
            relation_switching_service = SubElement(relation, "SwitchingService")
            relation_switching_service.set("id", "urn:ogf:network:surf.nl:2020:production:switch:EVTS.A-GOLE")
            relation_switching_service.set("labelSwapping", "true")
            relation_switching_service.set("labelType", "http://schemas.ogf.org/nml/2012/10/ethernet#vlan")
            relation_switching_service_definition = SubElement(
                relation_switching_service, QName(nsmap["sd"], "serviceDefinition")
            )
            relation_switching_service_definition.set("id", "urn:ogf:network:surf.nl:2020:production:sd:EVTS.A-GOLE")
            for port in ports:
                bidirectional_port = SubElement(topology, "BidirectionalPort")
                bidirectional_port.set("id", f"{network_id}:{port.name}")
                bidirectional_port_name = SubElement(bidirectional_port, "name")
                bidirectional_port_name.text = port.description
                bidirectional_port_group = SubElement(bidirectional_port, "PortGroup")
                bidirectional_port_group.set("id", f"{network_id}:{port.name}:in")
                bidirectional_port_group = SubElement(bidirectional_port, "PortGroup")
                bidirectional_port_group.set("id", f"{network_id}:{port.name}:out")
            relation = SubElement(topology, "Relation")
            relation.set("type", "http://schemas.ogf.org/nml/2013/05/base#hasInboundPort")
            for port in ports:
                relation_port_group = SubElement(relation, "PortGroup")
                relation_port_group.set("id", f"{network_id}:{port.name}:in")
                relation_port_group_label_group = SubElement(relation_port_group, "LabelGroup")
                relation_port_group_label_group.set("labeltype", "http://schemas.ogf.org/nml/2012/10/ethernet#vlan")
                relation_port_group_label_group.text = port.vlans
            relation = SubElement(topology, "Relation")
            relation.set("type", "http://schemas.ogf.org/nml/2013/05/base#hasOutboundPort")
            for port in ports:
                relation_port_group = SubElement(relation, "PortGroup")
                relation_port_group.set("id", f"{network_id}:{port.name}:out")
                relation_port_group_label_group = SubElement(relation_port_group, "LabelGroup")
                relation_port_group_label_group.set("labeltype", "http://schemas.ogf.org/nml/2012/10/ethernet#vlan")
                relation_port_group_label_group.text = port.vlans

        return tostring(topology, encoding="iso-8859-1", pretty_print=True)  # .decode('iso-8859-1')
