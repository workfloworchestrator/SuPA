import cherrypy
from cherrypy.test import helper
from lxml.etree import fromstring, tostring  # noqa: S410

from supa.documents.topology import TopologyEndpoint

topology = b"""<?xml version="1.0"?>
<ns3:Topology xmlns:ns3="http://schemas.ogf.org/nml/2013/05/base#" xmlns:ns4="http://schemas.ogf.org/nml/2012/10/ethernet" xmlns:ns5="http://schemas.ogf.org/nsi/2013/12/services/definition" id="urn:ogf:network:example.domain:2001:topology" version="2024-05-01T13:54:22+00:00">
  <ns3:name>example.domain topology</ns3:name>
  <ns3:Lifetime>
    <ns3:start>2024-05-01T13:54:22+00:00</ns3:start>
    <ns3:end>2024-05-08T13:54:22+00:00</ns3:end>
  </ns3:Lifetime>
  <ns3:BidirectionalPort id="urn:ogf:network:example.domain:2001:topology:port1">
    <ns3:name/>
    <ns3:PortGroup id="urn:ogf:network:example.domain:2001:topology:port1:in"/>
    <ns3:PortGroup id="urn:ogf:network:example.domain:2001:topology:port1:out"/>
  </ns3:BidirectionalPort>
  <ns3:BidirectionalPort id="urn:ogf:network:example.domain:2001:topology:port2">
    <ns3:name/>
    <ns3:PortGroup id="urn:ogf:network:example.domain:2001:topology:port2:in"/>
    <ns3:PortGroup id="urn:ogf:network:example.domain:2001:topology:port2:out"/>
  </ns3:BidirectionalPort>
  <ns3:BidirectionalPort id="urn:ogf:network:example.domain:2001:topology:enni.port1">
    <ns3:name>To external network</ns3:name>
    <ns3:PortGroup id="urn:ogf:network:example.domain:2001:topology:enni.port1:in"/>
    <ns3:PortGroup id="urn:ogf:network:example.domain:2001:topology:enni.port1:out"/>
  </ns3:BidirectionalPort>
  <ns3:BidirectionalPort id="urn:ogf:network:example.domain:2001:topology:enni.port2">
    <ns3:name/>
    <ns3:PortGroup id="urn:ogf:network:example.domain:2001:topology:enni.port2:in"/>
    <ns3:PortGroup id="urn:ogf:network:example.domain:2001:topology:enni.port2:out"/>
  </ns3:BidirectionalPort>
  <ns5:serviceDefinition id="urn:ogf:network:example.domain:2001:topology:sd:EVTS.A-GOLE">
    <name>GLIF Automated GOLE Ethernet VLAN Transfer Service</name>
    <serviceType>http://services.ogf.org/nsi/2013/12/descriptions/EVTS.A-GOLE</serviceType>
  </ns5:serviceDefinition>
  <ns3:Relation type="http://schemas.ogf.org/nml/2013/05/base#hasService">
    <ns3:SwitchingService encoding="http://schemas.ogf.org/nml/2012/10/ethernet" id="urn:ogf:network:example.domain:2001:topology:switch:EVTS.A-GOLE" labelSwapping="true" labelType="http://schemas.ogf.org/nml/2012/10/ethernet#vlan">
      <ns3:Relation type="http://schemas.ogf.org/nml/2013/05/base#hasInboundPort">
        <ns3:PortGroup id="urn:ogf:network:example.domain:2001:topology:port1:in"/>
        <ns3:PortGroup id="urn:ogf:network:example.domain:2001:topology:port2:in"/>
        <ns3:PortGroup id="urn:ogf:network:example.domain:2001:topology:enni.port1:in"/>
        <ns3:PortGroup id="urn:ogf:network:example.domain:2001:topology:enni.port2:in"/>
      </ns3:Relation>
      <ns3:Relation type="http://schemas.ogf.org/nml/2013/05/base#hasOutboundPort">
        <ns3:PortGroup id="urn:ogf:network:example.domain:2001:topology:port1:out"/>
        <ns3:PortGroup id="urn:ogf:network:example.domain:2001:topology:port2:out"/>
        <ns3:PortGroup id="urn:ogf:network:example.domain:2001:topology:enni.port1:out"/>
        <ns3:PortGroup id="urn:ogf:network:example.domain:2001:topology:enni.port2:out"/>
      </ns3:Relation>
      <ns5:serviceDefinition id="urn:ogf:network:example.domain:2001:topology:sd:EVTS.A-GOLE"/>
    </ns3:SwitchingService>
  </ns3:Relation>
  <ns3:Relation type="http://schemas.ogf.org/nml/2013/05/base#hasInboundPort">
    <ns3:PortGroup encoding="http://schemas.ogf.org/nml/2012/10/ethernet" id="urn:ogf:network:example.domain:2001:topology:port1:in">
      <ns3:LabelGroup labeltype="http://schemas.ogf.org/nml/2012/10/ethernet#vlan">1779-1799</ns3:LabelGroup>
      <ns4:capacity>1000000000</ns4:capacity>
      <ns4:granularity>1000000</ns4:granularity>
      <ns4:minimumReservableCapacity>1000000</ns4:minimumReservableCapacity>
      <ns4:maximumReservableCapacity>1000000000</ns4:maximumReservableCapacity>
    </ns3:PortGroup>
    <ns3:PortGroup encoding="http://schemas.ogf.org/nml/2012/10/ethernet" id="urn:ogf:network:example.domain:2001:topology:port2:in">
      <ns3:LabelGroup labeltype="http://schemas.ogf.org/nml/2012/10/ethernet#vlan">1779-1799</ns3:LabelGroup>
      <ns4:capacity>1000000000</ns4:capacity>
      <ns4:granularity>1000000</ns4:granularity>
      <ns4:minimumReservableCapacity>1000000</ns4:minimumReservableCapacity>
      <ns4:maximumReservableCapacity>1000000000</ns4:maximumReservableCapacity>
    </ns3:PortGroup>
    <ns3:PortGroup encoding="http://schemas.ogf.org/nml/2012/10/ethernet" id="urn:ogf:network:example.domain:2001:topology:enni.port1:in">
      <ns3:LabelGroup labeltype="http://schemas.ogf.org/nml/2012/10/ethernet#vlan">2-4094</ns3:LabelGroup>
      <ns3:Relation type="http://schemas.ogf.org/nml/2013/05/base#isAlias">
        <ns3:PortGroup id="urn:ogf:network:domain:1999:topology:neighbour-1-out"/>
      </ns3:Relation>
      <ns4:capacity>10000000000</ns4:capacity>
      <ns4:granularity>1000000</ns4:granularity>
      <ns4:minimumReservableCapacity>1000000</ns4:minimumReservableCapacity>
      <ns4:maximumReservableCapacity>10000000000</ns4:maximumReservableCapacity>
    </ns3:PortGroup>
    <ns3:PortGroup encoding="http://schemas.ogf.org/nml/2012/10/ethernet" id="urn:ogf:network:example.domain:2001:topology:enni.port2:in">
      <ns3:LabelGroup labeltype="http://schemas.ogf.org/nml/2012/10/ethernet#vlan">1000-1009</ns3:LabelGroup>
      <ns3:Relation type="http://schemas.ogf.org/nml/2013/05/base#isAlias">
        <ns3:PortGroup id="urn:ogf:network:domain:2024::3-out"/>
      </ns3:Relation>
      <ns4:capacity>10000000000</ns4:capacity>
      <ns4:granularity>1000000</ns4:granularity>
      <ns4:minimumReservableCapacity>1000000</ns4:minimumReservableCapacity>
      <ns4:maximumReservableCapacity>10000000000</ns4:maximumReservableCapacity>
    </ns3:PortGroup>
  </ns3:Relation>
  <ns3:Relation type="http://schemas.ogf.org/nml/2013/05/base#hasOutboundPort">
    <ns3:PortGroup encoding="http://schemas.ogf.org/nml/2012/10/ethernet" id="urn:ogf:network:example.domain:2001:topology:port1:out">
      <ns3:LabelGroup labeltype="http://schemas.ogf.org/nml/2012/10/ethernet#vlan">1779-1799</ns3:LabelGroup>
      <ns4:capacity>1000000000</ns4:capacity>
      <ns4:granularity>1000000</ns4:granularity>
      <ns4:minimumReservableCapacity>1000000</ns4:minimumReservableCapacity>
      <ns4:maximumReservableCapacity>1000000000</ns4:maximumReservableCapacity>
    </ns3:PortGroup>
    <ns3:PortGroup encoding="http://schemas.ogf.org/nml/2012/10/ethernet" id="urn:ogf:network:example.domain:2001:topology:port2:out">
      <ns3:LabelGroup labeltype="http://schemas.ogf.org/nml/2012/10/ethernet#vlan">1779-1799</ns3:LabelGroup>
      <ns4:capacity>1000000000</ns4:capacity>
      <ns4:granularity>1000000</ns4:granularity>
      <ns4:minimumReservableCapacity>1000000</ns4:minimumReservableCapacity>
      <ns4:maximumReservableCapacity>1000000000</ns4:maximumReservableCapacity>
    </ns3:PortGroup>
    <ns3:PortGroup encoding="http://schemas.ogf.org/nml/2012/10/ethernet" id="urn:ogf:network:example.domain:2001:topology:enni.port1:out">
      <ns3:LabelGroup labeltype="http://schemas.ogf.org/nml/2012/10/ethernet#vlan">2-4094</ns3:LabelGroup>
      <ns3:Relation type="http://schemas.ogf.org/nml/2013/05/base#isAlias">
        <ns3:PortGroup id="urn:ogf:network:domain:1999:topology:neighbour-1-in"/>
      </ns3:Relation>
      <ns4:capacity>10000000000</ns4:capacity>
      <ns4:granularity>1000000</ns4:granularity>
      <ns4:minimumReservableCapacity>1000000</ns4:minimumReservableCapacity>
      <ns4:maximumReservableCapacity>10000000000</ns4:maximumReservableCapacity>
    </ns3:PortGroup>
    <ns3:PortGroup encoding="http://schemas.ogf.org/nml/2012/10/ethernet" id="urn:ogf:network:example.domain:2001:topology:enni.port2:out">
      <ns3:LabelGroup labeltype="http://schemas.ogf.org/nml/2012/10/ethernet#vlan">1000-1009</ns3:LabelGroup>
      <ns3:Relation type="http://schemas.ogf.org/nml/2013/05/base#isAlias">
        <ns3:PortGroup id="urn:ogf:network:domain:2024::3-in"/>
      </ns3:Relation>
      <ns4:capacity>10000000000</ns4:capacity>
      <ns4:granularity>1000000</ns4:granularity>
      <ns4:minimumReservableCapacity>1000000</ns4:minimumReservableCapacity>
      <ns4:maximumReservableCapacity>10000000000</ns4:maximumReservableCapacity>
    </ns3:PortGroup>
  </ns3:Relation>
</ns3:Topology>
"""  # noqa: E501, B950


class SimpleCPTest(helper.CPWebCase):
    """Simple Cherry Pie test server."""

    helper.CPWebCase.interactive = False

    @staticmethod
    def setup_server() -> None:
        """Mount endpoint that needs to be tested."""
        cherrypy.tree.mount(TopologyEndpoint(), "/topology", {})

    def test_topology_document_generation(self) -> None:
        """Test the correct generation of the topology document."""
        page = self.getPage("/topology/")
        self.assertStatus("200 OK")
        actual_topology = fromstring(page[2])  # noqa: S320
        expected_topology = fromstring(topology)  # noqa: S320
        # remove version attribute from Topology and complete Lifetime element because the timestamps will never match
        actual_topology.attrib["version"] = ""
        lifetime = actual_topology.find("{http://schemas.ogf.org/nml/2013/05/base#}Lifetime")
        actual_topology.remove(lifetime)  # type: ignore[arg-type]
        expected_topology.attrib["version"] = ""
        lifetime = expected_topology.find("{http://schemas.ogf.org/nml/2013/05/base#}Lifetime")
        expected_topology.remove(lifetime)  # type: ignore[arg-type]

        assert tostring(actual_topology) == tostring(expected_topology)
