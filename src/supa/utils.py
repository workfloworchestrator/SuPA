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
"""Collection of various utility functions and data structures."""
import operator
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

NO_END_DATE = datetime(2108, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
"""A sufficiently far into the future date to be considered *no end date*

Date/time calculations are easier when we have an actual date to work with.
Hence, to model "no end date" we need to come up with a date
that is far enough into the future to be considered "forever".
Randomly picking a large number for the year of such a date feels inappropriate;
we can be a lot more geeky about it than that.

So, a somewhat geeky candidate is the first prime number after (the year) 2020.
That happens to be 2081;
61 years into the future.
Although we have high hopes for SuPA,
we don't expect it to last that long.
As such, it does meet the criterion to be considered "forever".
But the fact that it starts with "20xx
might not make it immediately obvious that this is the "no end date" date.

If we shuffle a bit with the digits of that prime number we get 2108.
A date that starts with "21xx" should make it sufficiently different
from all the other real end dates.
On top of that it is a somewhat a geeky date as well.
That is, if you like (military) SciFi
and have read The Frontlines Series by Marko Kloos,
which is set in the year 2108.
All criteria have now been met.
"""


def current_timestamp() -> datetime:
    """Return an "aware" UTC timestamp for "now".

    Returns:
        An "aware" UTC timestamp.
    """
    return datetime.now(timezone.utc)


@dataclass
class Stp:
    """Dataclass for representing the constituent parts of an STP identifier."""

    domain: str
    network_type: str
    port: str
    labels: Optional[str]


URN_PREFIX = "urn:ogf:network"
URN_PREFIX_LEN = len(URN_PREFIX)


def parse_stp(stp: str) -> Stp:
    """Parse STP identifier in its constituent parts.

    Args:
        stp: Identifier of the STP

    Returns:
        :class:`Stp` dataclass

    """
    parts = stp[URN_PREFIX_LEN + 1 :].split(":")  # +1 -> ":"  # noqa: E203
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
