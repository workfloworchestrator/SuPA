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
"""NSI specific functions and datastructures."""

import operator
from dataclasses import dataclass
from typing import Optional

from supa.util.vlan import VlanRanges

URN_PREFIX = "urn:ogf:network"
"""URN namespace for Network Resources."""

_URN_PREFIX_LEN = len(URN_PREFIX)


@dataclass
class Stp:
    """Dataclass for representing the constituent parts of an STP identifier."""

    domain: str
    topology: str
    stp_id: str
    labels: Optional[str]

    @property
    def vlan_ranges(self) -> VlanRanges:
        """Return the vlan ranges specified on the STP.

        A single
        If no vlan ranges where specified on the STP,
        this will return an "empty" :class:`~supa.util.vlan.VlanRanges` object.
        Such an object will evaluate to False in a boolean context.


        Returns:
            A :class:`~supa.util.vlan.VlanRanges` object.
        """
        if self.labels is not None and self.labels.startswith("vlan="):
            return VlanRanges(self.labels[len("vlan=") :])  # noqa: E203
        return VlanRanges()

    def __str__(self) -> str:
        """Return printable string representation of Stp."""
        stp = f"{URN_PREFIX}:{self.domain}:{self.topology}:{self.stp_id}"
        if self.labels:
            stp += f"?{self.labels}"
        return stp


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

    stp_id, *remainder = parts[-1].split("?")
    labels = remainder.pop() if remainder else None
    domain: str
    if (parts_len := len(parts)) == 4 and parts[1].isdigit():
        domain = f"{parts[0]}:{parts[1]}"  # eg: "example.domain" and "2013"
        topology = parts[2]

    # If we do have only three parts, non of them should be numerical (eg "2013").
    # If one or more are numerical it is an indication something else is missing.
    elif parts_len == 3 and not any(map(operator.methodcaller("isdigit"), parts)):
        domain = parts[0]
        topology = parts[1]
    else:
        raise ValueError(f"Not an STP: `{stp}`")

    return Stp(domain=domain, topology=topology, stp_id=stp_id, labels=labels)
