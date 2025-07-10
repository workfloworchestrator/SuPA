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
"""Generate a NSI discovery document.

Example discovery document::

    <?xml version='1.0' encoding='iso-8859-1'?>
    <nsa:nsa xmlns:nsa="http://schemas.ogf.org/nsi/2014/02/discovery/nsa"
             xmlns:vcard="urn:ietf:params:xml:ns:vcard-4.0">
      <name>My uPA</name>
      <adminContact>
        <vcard:vcard>
          <vcard:uid>
            <vcard:uri>https://host.example.domain/nsi/v2/provider#adminContact</vcard:uri>
          </vcard:uid>
          <vcard:prodid>
            <vcard:text>SuPA-host.example.domain</vcard:text>
          </vcard:prodid>
          <vcard:rev>
            <vcard:timestamp>20200527T180758Z</vcard:timestamp>
          </vcard:rev>
          <vcard:kind>
            <vcard:text>Individual</vcard:text>
          </vcard:kind>
          <vcard:fn>
            <vcard:text>Firstname Lastname</vcard:text>
          </vcard:fn>
          <vcard:n>
            <vcard:surname>Firstname<vcard:given>Lastname</vcard:given></vcard:surname>
          </vcard:n>
        </vcard:vcard>
      </adminContact>
      <location>
        <latitude>-0.374350</latitude>
        <longitude>-159.996719</longitude>
      </location>
      <networkId>urn:ogf:network:netherlight.net:2013:production7</networkId>
      <interface>
        <type>application/vnd.ogf.nsi.topology.v2+xml</type>
        <href>https://host.example.domain/nsi-topology/production7</href>
      </interface>
      <interface>
        <type>application/vnd.ogf.nsi.cs.v2.provider+soap</type>
        <href>https://host.example.domain/nsi/v2/provider</href>
      </interface>
      <feature type="vnd.ogf.nsi.cs.v2.role.uPA"/>
    </nsa:nsa>
"""
import importlib.metadata
from datetime import timedelta
from typing import Union

import cherrypy
from lxml.etree import Element, QName, SubElement, tostring  # noqa: S410

from supa import settings
from supa.util.timestamp import current_timestamp

"""Namespace map for discovery document."""
nsmap = {
    "nsa": "http://schemas.ogf.org/nsi/2014/02/discovery/nsa",
    "vcard": "urn:ietf:params:xml:ns:vcard-4.0",
}


class DiscoveryEndpoint(object):
    """A cherryPy application to generate a NSI discovery document."""

    @cherrypy.expose  # type: ignore[misc]
    def index(self) -> Union[str, bytes]:
        """Index returns the generated NSI discovery document."""
        nsa = Element(QName(nsmap["nsa"], "nsa"), nsmap=nsmap)
        nsa_name = SubElement(nsa, "name")
        software_version = SubElement(nsa, "softwareVersion")
        start_time = SubElement(nsa, "startTime")
        admin_contact = SubElement(nsa, "adminContact")
        vcard = SubElement(admin_contact, QName(nsmap["vcard"], "vcard"))
        vcard_uid = SubElement(vcard, QName(nsmap["vcard"], "uid"))
        vcard_uid_uri = SubElement(vcard_uid, QName(nsmap["vcard"], "uri"))
        vcard_prodid = SubElement(vcard, QName(nsmap["vcard"], "prodid"))
        vcard_prodid_text = SubElement(vcard_prodid, QName(nsmap["vcard"], "text"))
        vcard_rev = SubElement(vcard, QName(nsmap["vcard"], "rev"))
        vcard_rev_timestamp = SubElement(vcard_rev, QName(nsmap["vcard"], "timestamp"))
        vcard_kind = SubElement(vcard, QName(nsmap["vcard"], "kind"))
        vcard_kind_text = SubElement(vcard_kind, QName(nsmap["vcard"], "text"))
        vcard_fn = SubElement(vcard, QName(nsmap["vcard"], "fn"))
        vcard_fn_text = SubElement(vcard_fn, QName(nsmap["vcard"], "text"))
        vcard_n = SubElement(vcard, QName(nsmap["vcard"], "n"))
        vcard_n_surname = SubElement(vcard_n, QName(nsmap["vcard"], "surname"))
        vcard_n_given = SubElement(vcard_n, QName(nsmap["vcard"], "given"))
        location = SubElement(nsa, "location")
        nsa_latitude = SubElement(location, "latitude")
        nsa_longitude = SubElement(location, "longitude")
        network_id = SubElement(nsa, "networkId")
        topology_interface = SubElement(nsa, "interface")
        topology_type = SubElement(topology_interface, "type")
        topology_href = SubElement(topology_interface, "href")
        provider_interface = SubElement(nsa, "interface")
        provider_type = SubElement(provider_interface, "type")
        provider_href = SubElement(provider_interface, "href")
        SubElement(nsa, "feature", {"type": "vnd.ogf.nsi.cs.v2.role.uPA"})

        now = current_timestamp()

        nsa.set("id", settings.nsa_id)
        nsa.set("version", now.isoformat(timespec="seconds"))
        nsa.set("expires", (now + timedelta(weeks=1)).isoformat(timespec="seconds"))
        nsa_name.text = settings.nsa_name
        software_version.text = f"SuPA {importlib.metadata.version('SuPA')}"
        start_time.text = settings.nsa_start_time.isoformat(timespec="seconds")
        # A unique identifier for the object
        vcard_uid_uri.text = f"{settings.nsa_exposed_url}{settings.nsa_provider_path}#adminContact"
        # The identifier of the product that created the vCard object
        vcard_prodid_text.text = f"SuPA-{settings.nsa_host}"
        # The revision datetime of the vCard object yyyymmddTHHMMSSZ
        vcard_rev_timestamp.text = settings.nsa_owner_timestamp
        vcard_kind_text.text = "Individual"
        vcard_fn_text.text = f"{settings.nsa_owner_firstname} {settings.nsa_owner_lastname}"
        vcard_n_surname.text = settings.nsa_owner_lastname
        vcard_n_given.text = settings.nsa_owner_firstname
        nsa_latitude.text = settings.nsa_latitude
        nsa_longitude.text = settings.nsa_longitude
        network_id.text = f"urn:ogf:network:{settings.domain}:{settings.topology}"
        topology_type.text = "application/vnd.ogf.nsi.topology.v2+xml"
        topology_href.text = f"{settings.nsa_exposed_url}{settings.nsa_topology_path}"
        provider_type.text = "application/vnd.ogf.nsi.cs.v2.provider+soap"
        provider_href.text = f"{settings.nsa_provider_exposed_url}{settings.nsa_provider_path}"

        return tostring(nsa, encoding="iso-8859-1", pretty_print=True)  # .decode('iso-8859-1')
