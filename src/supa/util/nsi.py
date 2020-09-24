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
import operator
from dataclasses import dataclass
from typing import Optional


@dataclass
class Stp:
    """Dataclass for representing the constituent parts of an STP identifier."""

    domain: str
    network_type: str
    port: str
    labels: Optional[str]


URN_PREFIX = "urn:ogf:network"
"""URN namespace for Network Resources."""

_URN_PREFIX_LEN = len(URN_PREFIX)


def parse_stp(stp: str) -> Stp:
    """Parse STP identifier in its constituent parts.

    Args:
        stp: Identifier of the STP

    Returns:
        object:
        :class:`Stp` dataclass

    """
    parts = stp[_URN_PREFIX_LEN + 1 :].split(":")  # +1 -> ":"  # noqa: E203
    if not all(parts):
        raise ValueError(f"Not an STP: `{stp}`")

    port, *remainder = parts[-1].split("?")
    labels = remainder.pop() if remainder else None
    domain: str
    if (parts_len := len(parts)) == 4 and parts[1].isdigit():
        domain = f"{parts[0]}:{parts[1]}"  # eg: "netherlight.net" and "2013"
        network_type = parts[2]

    # If we do have only three parts, non of them should be numerical (eg "2013").
    # If one or more are numerical it is an indication something else is missing.
    elif parts_len == 3 and not any(map(operator.methodcaller("isdigit"), parts)):
        domain = parts[0]
        network_type = parts[1]
    else:
        raise ValueError(f"Not an STP: `{stp}`")

    return Stp(domain=domain, network_type=network_type, port=port, labels=labels)
