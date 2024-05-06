import importlib.metadata

import cherrypy
from cherrypy.test import helper
from lxml.etree import fromstring, tostring  # noqa: S410

from supa.documents.discovery import DiscoveryEndpoint

discovery = b"""<?xml version=\'1.0\' encoding=\'iso-8859-1\'?>
<nsa:nsa xmlns:nsa="http://schemas.ogf.org/nsi/2014/02/discovery/nsa" xmlns:vcard="urn:ietf:params:xml:ns:vcard-4.0" id="urn:ogf:network:example.domain:2001:nsa:supa" version="2024-05-06T08:24:33+00:00" expires="2024-05-13T08:24:33+00:00">
  <name>example.domain uPA</name>
  <softwareVersion>SuPA 0.2.3.dev1</softwareVersion>
  <startTime>2024-05-06T08:24:32+00:00</startTime>
  <adminContact>
    <vcard:vcard>
      <vcard:uid>
        <vcard:uri>http://localhost:8080/provider#adminContact</vcard:uri>
      </vcard:uid>
      <vcard:prodid>
        <vcard:text>SuPA-localhost</vcard:text>
      </vcard:prodid>
      <vcard:rev>
        <vcard:timestamp>19700101T000000Z</vcard:timestamp>
      </vcard:rev>
      <vcard:kind>
        <vcard:text>Individual</vcard:text>
      </vcard:kind>
      <vcard:fn>
        <vcard:text>Firstname Lastname</vcard:text>
      </vcard:fn>
      <vcard:n>
        <vcard:surname>Lastname</vcard:surname>
        <vcard:given>Firstname</vcard:given>
      </vcard:n>
    </vcard:vcard>
  </adminContact>
  <location>
    <latitude>-0.374350</latitude>
    <longitude>-159.996719</longitude>
  </location>
  <networkId>urn:ogf:network:example.domain:2001:topology</networkId>
  <interface>
    <type>application/vnd.ogf.nsi.topology.v2+xml</type>
    <href>http://localhost:8080/topology</href>
  </interface>
  <interface>
    <type>application/vnd.ogf.nsi.cs.v2.provider+soap</type>
    <href>http://localhost:8080/provider</href>
  </interface>
  <feature type="vnd.ogf.nsi.cs.v2.role.uPA"/>
</nsa:nsa>
"""  # noqa: E501, B950


class SimpleCPTest(helper.CPWebCase):
    """Simple Cherry Pie test server."""

    @staticmethod
    def setup_server() -> None:
        """Mount endpoint that needs to be tested."""
        cherrypy.tree.mount(DiscoveryEndpoint(), "/discovery", {})

    def test_discovery_document_generation(self) -> None:
        """Test the correct generation of the discovery document."""
        page = self.getPage("/discovery/")
        self.assertStatus("200 OK")
        actual_discovery = fromstring(page[2])  # noqa: S320
        expected_discovery = fromstring(discovery)  # noqa: S320
        # remove  from nsa element because the timestamps will never match
        actual_discovery.attrib["version"] = ""
        actual_discovery.attrib["expires"] = ""
        expected_discovery.attrib["version"] = ""
        expected_discovery.attrib["expires"] = ""
        # set latest software version on expected discovery document
        software_version = expected_discovery.find("softwareVersion")
        software_version.text = f"SuPA {importlib.metadata.version('SuPA')}"  # type: ignore[union-attr]
        # remove startTime element because the timestamps will never match
        start_time = actual_discovery.find("startTime")
        actual_discovery.remove(start_time)  # type: ignore[arg-type]
        start_time = expected_discovery.find("startTime")
        expected_discovery.remove(start_time)  # type: ignore[arg-type]

        assert tostring(actual_discovery) == tostring(expected_discovery)
