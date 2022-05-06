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
from typing import Any

import cherrypy
from cherrypy import config, engine, tree

from supa.documents.discovery import Discovery


def _error_page_404(status, message, traceback, version):  # type: ignore[no-untyped-def]
    """Empty cherrypy 404 error page."""
    return ""


def _init_cherrypy() -> Any:
    """Initialize the cherrypy webserver and mount the discovery and topology applications."""
    server_config = {
        "server.socket_host": "127.0.0.1",
        "server.socket_port": 4321,
        # 'server.ssl_certificate':'cert.pem',
        # 'server.ssl_private_key':'privkey.pem',
        "engine.autoreload.on": False,
        "log.screen": False,
        "checker.on": False,
        "tools.log_headers.on": False,
        "request.show_tracebacks": False,
        "request.show_mismatched_params": False,
        "error_page.404": _error_page_404,
    }
    app_config = {
        "/": {
            "tools.response_headers.on": True,
            "tools.response_headers.headers": [("Content-Type", "application/xml")],
        }
    }
    config.update(server_config)
    cherrypy._cplogging.LogManager.access_log_format = '{h} {l} {u} "{r}" {s} {b} "{f}" "{a}"'
    tree.mount(Discovery(), "/", app_config)
    return engine


webengine = _init_cherrypy()
