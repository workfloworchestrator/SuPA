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

Example topology document::

    <?xml version='1.0' encoding='iso-8859-1'?>
    <ns3:Topology xmlns:ns3="http://schemas.ogf.org/nml/2013/05/base#"
                  xmlns:ns5="http://schemas.ogf.org/nsi/2013/12/services/definition"
                  id="urn:ogf:network:example.domain:2001:topology"
                  version="2022-06-06T13:25:37+00:00">

      <ns3:name>example.domain topology</ns3:name>
      <ns3:Lifetime>
        <ns3:start>2022-06-06T13:25:37+00:00</ns3:start>
        <ns3:end>2022-06-13T13:25:37+00:00</ns3:end>
      </ns3:Lifetime>

      <ns3:BidirectionalPort id="urn:ogf:network:example.domain:2001:topology:port1">
        <ns3:name>port description</ns3:name>
        <ns3:PortGroup id="urn:ogf:network:example.domain:2001:topology:port1:in"/>
        <ns3:PortGroup id="urn:ogf:network:example.domain:2001:topology:port1:out"/>
      </ns3:BidirectionalPort>

      <ns5:serviceDefinition id="urn:ogf:network:example.domain:2001:topology:sd:EVTS.A-GOLE">
        <name>GLIF Automated GOLE Ethernet VLAN Transfer Service</name>
        <serviceType>http://services.ogf.org/nsi/2013/12/descriptions/EVTS.A-GOLE</serviceType>
      </ns5:serviceDefinition>
      <ns3:Relation type="http://schemas.ogf.org/nml/2013/05/base#hasService">
        <ns3:SwitchingService encoding="http://schemas.ogf.org/nml/2012/10/ethernet"
                              id="urn:ogf:network:example.domain:2001:topology:switch:EVTS.A-GOLE"
                              labelSwapping="true"
                              labelType="http://schemas.ogf.org/nml/2012/10/ethernet#vlan">
          <ns3:Relation type="http://schemas.ogf.org/nml/2013/05/base#hasInboundPort">
            <ns3:PortGroup id="urn:ogf:network:example.domain:2001:topology:port1:in"/>
          </ns3:Relation>
          <ns3:Relation type="http://schemas.ogf.org/nml/2013/05/base#hasOutboundPort">
            <ns3:PortGroup id="urn:ogf:network:example.domain:2001:topology:port1:out"/>
          </ns3:Relation>
          <ns5:serviceDefinition id="urn:ogf:network:example.domain:2001:topology:sd:EVTS.A-GOLE"/>
        </ns3:SwitchingService>
      </ns3:Relation>

      <ns3:Relation type="http://schemas.ogf.org/nml/2013/05/base#hasInboundPort">
        <ns3:PortGroup encoding="http://schemas.ogf.org/nml/2012/10/ethernet"
                       id="urn:ogf:network:example.domain:2001:topology:port1:in">
          <ns3:LabelGroup labeltype="http://schemas.ogf.org/nml/2012/10/ethernet#vlan">1779-1799</ns3:LabelGroup>
        </ns3:PortGroup>
      </ns3:Relation>
      <ns3:Relation type="http://schemas.ogf.org/nml/2013/05/base#hasOutboundPort">
        <ns3:PortGroup encoding="http://schemas.ogf.org/nml/2012/10/ethernet"
                       id="urn:ogf:network:example.domain:2001:topology:port1:out">
          <ns3:LabelGroup labeltype="http://schemas.ogf.org/nml/2012/10/ethernet#vlan">1779-1799</ns3:LabelGroup>
        </ns3:PortGroup>
      </ns3:Relation>

    </ns3:Topology>
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

# TODO The ability to fetch topology is used in the healthcheck, in K8S the default timeout of liveness
#      and readiness probes is 1 second, but fetching topology from the NRM can take much longer than that,
#      resulting in periodic Unhealthy states on the pod.
#      It would probably be better to move the topology refresh to a job and add a second configuration
#      parameter topology_refresh_interval, when setting topology_refresh_interval to 60 seconds and
#      topology_freshness to 120 seconds would allow a 60 second period to fetch topology form the NRM.


def refresh_topology() -> None:
    """Refresh list of STP's in the database with topology from NRM.

    Skip refresh if configured for manual topology,
    also skip if topology has been refreshed withing `topology_freshness` seconds.
    """
    from supa.documents import refresh_topology_lock

    global last_refresh
    if settings.manual_topology:
        log.debug("skipping topology refresh", manual_topology=settings.manual_topology)
        return
    if refresh_topology_lock.acquire(timeout=60):
        log.debug("refresh topology lock", state="acquired")
    else:
        log.warning("refresh topology lock", state="failed to acquire")
        return
    if (now := current_timestamp()) < last_refresh + timedelta(seconds=settings.topology_freshness):
        log.debug(
            "topology is still fresh",
            last_refresh=last_refresh.isoformat(timespec="seconds"),
            now=now.isoformat(timespec="seconds"),
            topology_freshness=settings.topology_freshness,
        )
        refresh_topology_lock.release()
        log.debug("refresh topology lock", state="released")
        return
    log.debug(
        "refreshing topology",
        last_refresh=last_refresh.isoformat(timespec="seconds"),
        now=now.isoformat(timespec="seconds"),
    )

    from supa.db.session import db_session
    from supa.nrm.backend import backend

    try:
        nrm_stps = backend.topology()
    except Exception as exception:
        refresh_topology_lock.release()
        log.warning("refresh topology lock", state="released after exception")
        raise exception
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
                log.info("disable vanished STP", stp_id=stp.stp_id, port_id=stp.port_id, vlans=stp.vlans)
                stp.enabled = False
    last_refresh = now
    refresh_topology_lock.release()
    log.debug("refresh topology lock", state="released")


"""Namespace map for topology document."""
nsmap = {
    "ns3": "http://schemas.ogf.org/nml/2013/05/base#",
    "ns4": "http://schemas.ogf.org/nml/2012/10/ethernet",
    "ns5": "http://schemas.ogf.org/nsi/2013/12/services/definition",
}


class TopologyEndpoint(object):
    """A cherryPy application to generate a NSI topology document."""

    @cherrypy.expose  # type: ignore[untyped-decorator]
    def index(self) -> Union[str, bytes]:
        """Index returns the generated NSI topology document."""
        refresh_topology()
        network_id = f"urn:ogf:network:{settings.domain}:{settings.topology}"
        now = current_timestamp()

        from supa.db.session import db_session

        with db_session() as session:
            stps = session.query(Topology).filter(Topology.enabled)

            # topology
            topology = Element(QName(nsmap["ns3"], "Topology"), nsmap=nsmap)
            topology.set("id", network_id)
            topology.set("version", now.isoformat(timespec="seconds"))
            # name + lifetime
            name = SubElement(topology, QName(nsmap["ns3"], "name"))
            name.text = settings.topology_name
            lifetime = SubElement(topology, QName(nsmap["ns3"], "Lifetime"))
            lifetime_start = SubElement(lifetime, QName(nsmap["ns3"], "start"))
            lifetime_start.text = now.isoformat(timespec="seconds")
            lifetime_end = SubElement(lifetime, QName(nsmap["ns3"], "end"))
            lifetime_end.text = (now + timedelta(weeks=1)).isoformat(timespec="seconds")
            # BidirectionalPort's
            for stp in stps:
                bidirectional_port = SubElement(topology, QName(nsmap["ns3"], "BidirectionalPort"))
                bidirectional_port.set("id", f"{network_id}:{stp.stp_id}")
                bidirectional_port_name = SubElement(bidirectional_port, QName(nsmap["ns3"], "name"))
                bidirectional_port_name.text = stp.description
                bidirectional_port_group = SubElement(bidirectional_port, QName(nsmap["ns3"], "PortGroup"))
                bidirectional_port_group.set("id", f"{network_id}:{stp.stp_id}:in")
                bidirectional_port_group = SubElement(bidirectional_port, QName(nsmap["ns3"], "PortGroup"))
                bidirectional_port_group.set("id", f"{network_id}:{stp.stp_id}:out")
            # serviceDefinition
            service_definition = SubElement(topology, QName(nsmap["ns5"], "serviceDefinition"))
            service_definition.set("id", f"{network_id}:sd:EVTS.A-GOLE")
            service_definition_name = SubElement(service_definition, "name")
            service_definition_name.text = "GLIF Automated GOLE Ethernet VLAN Transfer Service"
            service_definition_service_type = SubElement(service_definition, "serviceType")
            service_definition_service_type.text = "http://services.ogf.org/nsi/2013/12/descriptions/EVTS.A-GOLE"
            relation = SubElement(topology, QName(nsmap["ns3"], "Relation"))
            relation.set("type", "http://schemas.ogf.org/nml/2013/05/base#hasService")
            relation_sw = SubElement(relation, QName(nsmap["ns3"], "SwitchingService"))
            relation_sw.set("encoding", "http://schemas.ogf.org/nml/2012/10/ethernet")
            relation_sw.set("id", f"{network_id}:switch:EVTS.A-GOLE")
            relation_sw.set("labelSwapping", "true" if settings.label_swapping else "false")
            relation_sw.set("labelType", "http://schemas.ogf.org/nml/2012/10/ethernet#vlan")
            for relation_type, suffix in (
                ("http://schemas.ogf.org/nml/2013/05/base#hasInboundPort", "in"),
                ("http://schemas.ogf.org/nml/2013/05/base#hasOutboundPort", "out"),
            ):
                relation_sw_port = SubElement(relation_sw, QName(nsmap["ns3"], "Relation"))
                relation_sw_port.set("type", relation_type)
                for stp in stps:
                    port_group = SubElement(relation_sw_port, QName(nsmap["ns3"], "PortGroup"))
                    port_group.set("id", f"{network_id}:{stp.stp_id}:{suffix}")
            relation_switching_sd = SubElement(relation_sw, QName(nsmap["ns5"], "serviceDefinition"))
            relation_switching_sd.set("id", f"{network_id}:sd:EVTS.A-GOLE")
            # inbound and outbound PortGroup's
            for relation_type, suffix in (
                ("http://schemas.ogf.org/nml/2013/05/base#hasInboundPort", "in"),
                ("http://schemas.ogf.org/nml/2013/05/base#hasOutboundPort", "out"),
            ):
                relation = SubElement(topology, QName(nsmap["ns3"], "Relation"))
                relation.set("type", relation_type)
                for stp in stps:
                    relation_port_group = SubElement(relation, QName(nsmap["ns3"], "PortGroup"))
                    relation_port_group.set("encoding", "http://schemas.ogf.org/nml/2012/10/ethernet")
                    relation_port_group.set("id", f"{network_id}:{stp.stp_id}:{suffix}")
                    # LabelGroup
                    relation_port_group_label_group = SubElement(relation_port_group, QName(nsmap["ns3"], "LabelGroup"))
                    relation_port_group_label_group.set("labeltype", "http://schemas.ogf.org/nml/2012/10/ethernet#vlan")
                    relation_port_group_label_group.text = stp.vlans
                    # isAlias
                    if stp.is_alias_in and stp.is_alias_out:
                        relation_port_group_relation = SubElement(relation_port_group, QName(nsmap["ns3"], "Relation"))
                        relation_port_group_relation.set("type", "http://schemas.ogf.org/nml/2013/05/base#isAlias")
                        relation_port_group_relation_port_group = SubElement(
                            relation_port_group_relation, QName(nsmap["ns3"], "PortGroup")
                        )
                        relation_port_group_relation_port_group.set(
                            "id", stp.is_alias_in if suffix == "in" else stp.is_alias_out
                        )
                    # capacity extension
                    relation_port_group_capacity = SubElement(relation_port_group, QName(nsmap["ns4"], "capacity"))
                    relation_port_group_capacity.text = str(stp.bandwidth * 1000000)
                    relation_port_group_granularity = SubElement(
                        relation_port_group, QName(nsmap["ns4"], "granularity")
                    )
                    relation_port_group_granularity.text = str(1000000)
                    relation_port_group_minimumReservableCapacity = SubElement(
                        relation_port_group, QName(nsmap["ns4"], "minimumReservableCapacity")
                    )
                    relation_port_group_minimumReservableCapacity.text = str(1000000)
                    relation_port_group_maximumReservableCapacity = SubElement(
                        relation_port_group, QName(nsmap["ns4"], "maximumReservableCapacity")
                    )
                    relation_port_group_maximumReservableCapacity.text = str(stp.bandwidth * 1000000)

        return tostring(topology, encoding="iso-8859-1", pretty_print=True)  # .decode('iso-8859-1')
