#  Copyright 2022 SURF.
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
"""Healthcheck endpoint."""

from typing import Union

import cherrypy
from htmlgen import Document, Heading, Paragraph

from supa.documents.topology import refresh_topology
from supa.job.shared import NsiException


def _check_topology() -> bool:
    """Verify if it is possible to fetch the topology."""
    try:
        refresh_topology()
    except NsiException:
        return False
    else:
        return True


class HealthcheckEndpoint(object):
    """A cherryPy application to generate a healthcheck document."""

    @cherrypy.expose  # type: ignore[misc]
    def index(self) -> Union[str, bytes]:
        """Index returns the generated healthcheck document."""
        document = Document("SuPA healthcheck")
        document.append_body(Heading(3, "SuPA healthcheck"))
        if healthy_topology := _check_topology():
            document.append_body(Paragraph("NRM topology: OK"))
        else:
            document.append_body(Paragraph("NRM topology: FAIL"))

        if not healthy_topology:
            cherrypy.response.status = 503
            cherrypy.response.headers["Retry-After"] = 60
        return bytes(str(document), "utf-8")
