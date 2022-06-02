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
"""Initialize cherrypy to serve discovery and topology documents."""
from logging import Filter
from typing import Any

import cherrypy
from cherrypy import config, engine, tree

from supa import settings
from supa.documents.discovery import DiscoveryEndpoint
from supa.documents.healthcheck import HealthcheckEndpoint
from supa.documents.topology import TopologyEndpoint


def _error_page_404(status, message, traceback, version):  # type: ignore[no-untyped-def]
    """Empty cherrypy 404 error page."""
    return ""


class _IgnoreURLFilter(Filter):
    """Simple log message filtering."""

    def __init__(self, ignore: str):
        """Ignore GET requests on `ignore`."""
        self.ignore = "GET /" + ignore

    def filter(self, record: Any) -> bool:  # noqa: A003
        """Filter ignored GET requests."""
        return self.ignore not in record.getMessage()


def _init_cherrypy() -> Any:
    """Initialize the cherrypy webserver and mount the discovery and topology applications."""
    config.update(
        {
            "server.socket_host": settings.document_server_host,
            "server.socket_port": settings.document_server_port,
            # 'server.ssl_certificate':'cert.pem',
            # 'server.ssl_private_key':'privkey.pem',
            "engine.autoreload.on": False,
            "log.screen": False,
            "checker.on": False,
            "tools.log_headers.on": False,
            "request.show_tracebacks": False,
            "request.show_mismatched_params": False,
            "error_page.404": _error_page_404,
            "tools.response_headers.on": True,
            "tools.response_headers.headers": [("Content-Type", "application/xml")],
            "tools.trailing_slash.on": False,
        }
    )
    cherrypy._cplogging.LogManager.access_log_format = '{h} {l} {u} "{r}" {s} {b} "{f}" "{a}"'
    tree.mount(DiscoveryEndpoint(), "/discovery")
    tree.mount(TopologyEndpoint(), "/topology")
    tree.mount(
        HealthcheckEndpoint(),
        "/healthcheck",
        {
            "/": {
                "tools.response_headers.headers": [("Content-Type", "text/html")],
            }
        },
    ).log.access_log.addFilter(_IgnoreURLFilter("healthcheck"))

    return engine


webengine = _init_cherrypy()
