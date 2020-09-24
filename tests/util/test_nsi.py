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

import pytest

from supa.util.nsi import parse_stp


def test_parse_stp_with_year_unqualified() -> None:
    stp = parse_stp("urn:ogf:network:netherlight.net:2013:production7:netherlight-of-1?vlan=200-500,1779-1799")
    assert stp.domain == "netherlight.net:2013"
    assert stp.network_type == "production7"
    assert stp.port == "netherlight-of-1"
    assert stp.labels == "vlan=200-500,1779-1799"


def test_parse_stp_without_year_unqualified() -> None:
    stp = parse_stp("urn:ogf:network:netherlight.net:production7:netherlight-of-1?vlan=200-500,1779-1799")
    assert stp.domain == "netherlight.net"  # <-- without year
    assert stp.network_type == "production7"
    assert stp.port == "netherlight-of-1"
    assert stp.labels == "vlan=200-500,1779-1799"


def test_parse_stp_with_year_qualified() -> None:
    stp = parse_stp("urn:ogf:network:netherlight.net:2013:production7:netherlight-of-1?vlan=1779")
    assert stp.domain == "netherlight.net:2013"
    assert stp.network_type == "production7"
    assert stp.port == "netherlight-of-1"
    assert stp.labels == "vlan=1779"  # <-- qualified


def test_parse_stp_with_year_no_labels() -> None:
    stp = parse_stp("urn:ogf:network:netherlight.net:2013:production7:netherlight-of-1")
    assert stp.domain == "netherlight.net:2013"
    assert stp.network_type == "production7"
    assert stp.port == "netherlight-of-1"
    assert stp.labels is None  # <-- no labels


def test_parse_stp_missing_network_type() -> None:
    with pytest.raises(ValueError):
        parse_stp("urn:ogf:network:netherlight.net:2013:netherlight-of-1?vlan=200-500,1779-1799")


def test_parse_stp_missing_port() -> None:
    with pytest.raises(ValueError):
        parse_stp("urn:ogf:network:netherlight.net:2013:production7")


def test_parse_stp_missing_domain() -> None:
    with pytest.raises(ValueError):
        parse_stp("urn:ogf:network:2013:production7:netherlight-of-1?vlan=200-500,1779-1799")
