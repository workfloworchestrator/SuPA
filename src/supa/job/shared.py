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
from __future__ import annotations

from abc import ABCMeta, abstractmethod
from typing import ClassVar, Dict, List, Optional, Type

from supa.connection.error import NsiError, Variable


class Job(metaclass=ABCMeta):
    registry: ClassVar[List[Type[Job]]] = []

    @classmethod
    def __init_subclass__(cls: Type[Job]) -> None:
        super().__init_subclass__()
        cls.registry.append(cls)

    @abstractmethod
    def __call__(self) -> None:
        pass

    @classmethod
    @abstractmethod
    def recover(cls) -> List[Job]:
        pass


class NsiException(Exception):
    """Exception used in signalling NSI errors within SuPA.

    NSI errors are instances of :class:`~supa.connection.error.NsiError`.
    They represent a class or errors.
    :exc:`NsiException`, on the other hand,
    is used to represent a specific occurrence of an :class:`~supa.connection.error.NsiError`
    with extra information about the error.
    In addition it, being an exception, can be used to interrupt the regular flow of execution.

    An :exc:`NsiException` will eventually be converted into a ``ServiceException``.
    That is a Protobuf data structure/message that will be send back to the NSA/Aggregator.
    Hence an :exc:`NsiException` is internal.
    An ``ServiceException`` is external.
    """

    nsi_error: NsiError
    """Type of error that occurred."""

    extra_info: str
    """Extra information about the specifics of the error that occurred."""

    variables: Dict[Variable, str]
    """Additional information about the specifics of the error that occurred.

    The difference between :attr:`extra_info` and :attr:`variables`
    is that the former in primarily meant to provide a meaningful message to the end user.
    Whereas the latter is intended as a *a structured machine readable version*  of :attr:`extra_info`.

    This difference is of importance
    when the :exc:`NsiException` is converted into it's Protobuf equivalent: the ``ServiceException``.
    """

    def __init__(self, nsi_error: NsiError, extra_info: str, variables: Optional[Dict[Variable, str]] = None) -> None:
        super().__init__(nsi_error, extra_info, variables)
        self.nsi_error = nsi_error
        self.extra_info = extra_info
        self.variables = variables if variables is not None else {}

    @property
    def text(self) -> str:
        """Return text message of the exception/error.

        This combines information from the attached :class:`~supa.connection.error.NsiError`
        and the :attr:`etxra_info`.

        """
        return f"{self.nsi_error.error_code}: {self.nsi_error.descriptive_text} ({self.extra_info})"

    def __str__(self) -> str:
        return self.text
