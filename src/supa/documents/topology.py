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

TODO include example topology document
"""
from datetime import datetime, timedelta
from typing import Union

import cherrypy
import structlog
from lxml.etree import Element, QName, SubElement, tostring  # noqa: S410

from supa import settings
from supa.db.model import Topology
from supa.util.timestamp import EPOCH, current_timestamp

log = structlog.get_logger(__name__)
last_refresh: datetime = EPOCH


def refresh_topology() -> None:
    """Refresh list of STP's in the database with topology from NRM.

    Skip refresh if configured for manual topology,
    also skip if topology has been refreshed withing `topology_freshness` seconds.
    """
    global last_refresh
    if settings.manual_topology:
        log.debug("skipping topology refresh", manual_topology=settings.manual_topology)
        return
    if (now := current_timestamp()) < last_refresh + timedelta(seconds=settings.topology_freshness):
        log.debug(
            "topology is still fresh",
            last_refresh=last_refresh.isoformat(timespec="seconds"),
            now=now.isoformat(timespec="seconds"),
            topology_freshness=settings.topology_freshness,
        )
        return
    log.debug(
        "refreshing topology",
        last_refresh=last_refresh.isoformat(timespec="seconds"),
        now=now.isoformat(timespec="seconds"),
    )

    from supa.db.session import db_session
    from supa.nrm.backend import backend

    nrm_stps = backend.topology()
    nrm_stp_ids = [nrm_stp.stp_id for nrm_stp in nrm_stps]

    with db_session() as session:
        for nrm_stp in nrm_stps:
            if nrm_stp.topology != settings.topology:
                log.debug("skip STP with unknown topology", stp=nrm_stp.stp_id, topology=nrm_stp.topology)
            else:
                stp = session.query(Topology).filter(Topology.stp_id == nrm_stp.stp_id).one_or_none()
                if stp:
                    log.debug(
                        "update existing STP", stp_id=nrm_stp.stp_id, port_id=nrm_stp.port_id, vlans=nrm_stp.vlans
                    )
                    stp.port_id = nrm_stp.port_id
                    stp.vlans = nrm_stp.vlans
                    stp.description = nrm_stp.description
                    stp.is_alias_in = nrm_stp.is_alias_in
                    stp.is_alias_out = nrm_stp.is_alias_out
                    stp.bandwidth = nrm_stp.bandwidth
                    stp.enabled = nrm_stp.enabled
                else:
                    log.info("add new STP", stp_id=nrm_stp.stp_id, port_id=nrm_stp.port_id, vlans=nrm_stp.vlans)
                    session.add(
                        Topology(
                            stp_id=nrm_stp.stp_id,
                            port_id=nrm_stp.port_id,
                            vlans=nrm_stp.vlans,
                            description=nrm_stp.description,
                            is_alias_in=nrm_stp.is_alias_in,
                            is_alias_out=nrm_stp.is_alias_out,
                            bandwidth=nrm_stp.bandwidth,
                            enabled=nrm_stp.enabled,
                        )
                    )
        for stp in session.query(Topology).filter(Topology.enabled):
            if stp.stp_id not in nrm_stp_ids:
                log.info("disable vanished STP", stp_id=stp.stp_id, port_id=nrm_stp.port_id, vlans=nrm_stp.vlans)
                stp.enabled = False
    last_refresh = now


"""Namespace map for topology document."""
nsmap = {
    "topo": "http://schemas.ogf.org/nml/2013/05/base#",
    "sd": "http://schemas.ogf.org/nsi/2013/12/services/definition",
}


class TopologyEndpoint(object):
    """A cherryPy application to generate a NSI topology document."""

    @cherrypy.expose  # type: ignore[misc]
    def index(self) -> Union[str, bytes]:
        """Index returns the generated NSI topology document."""
        refresh_topology()
        network_id = f"urn:ogf:network:{settings.domain}:{settings.topology}"
        now = current_timestamp()

        from supa.db.session import db_session

        with db_session() as session:
            stps = session.query(Topology).filter(Topology.enabled)

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
            for stp in stps:
                bidirectional_port = SubElement(topology, "BidirectionalPort")
                bidirectional_port.set("id", f"{network_id}:{stp.stp_id}")
                bidirectional_port_name = SubElement(bidirectional_port, "name")
                bidirectional_port_name.text = stp.description
                bidirectional_port_group = SubElement(bidirectional_port, "PortGroup")
                bidirectional_port_group.set("id", f"{network_id}:{stp.stp_id}:in")
                bidirectional_port_group = SubElement(bidirectional_port, "PortGroup")
                bidirectional_port_group.set("id", f"{network_id}:{stp.stp_id}:out")
            relation = SubElement(topology, "Relation")
            relation.set("type", "http://schemas.ogf.org/nml/2013/05/base#hasInboundPort")
            for stp in stps:
                relation_port_group = SubElement(relation, "PortGroup")
                relation_port_group.set("id", f"{network_id}:{stp.stp_id}:in")
                relation_port_group_label_group = SubElement(relation_port_group, "LabelGroup")
                relation_port_group_label_group.set("labeltype", "http://schemas.ogf.org/nml/2012/10/ethernet#vlan")
                relation_port_group_label_group.text = stp.vlans
            relation = SubElement(topology, "Relation")
            relation.set("type", "http://schemas.ogf.org/nml/2013/05/base#hasOutboundPort")
            for stp in stps:
                relation_port_group = SubElement(relation, "PortGroup")
                relation_port_group.set("id", f"{network_id}:{stp.stp_id}:out")
                relation_port_group_label_group = SubElement(relation_port_group, "LabelGroup")
                relation_port_group_label_group.set("labeltype", "http://schemas.ogf.org/nml/2012/10/ethernet#vlan")
                relation_port_group_label_group.text = stp.vlans

        return tostring(topology, encoding="iso-8859-1", pretty_print=True)  # .decode('iso-8859-1')
