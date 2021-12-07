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

from apscheduler.triggers.date import DateTrigger

from supa.connection.error import NsiError, Variable


class Job(metaclass=ABCMeta):
    """Capture SuPA's asynchronous work.

    .. note::

        With asynchronous we don't mean async IO, as is all the hype these days.
        Instead, we refer to all the work that happens outside of the regular gRPC request/response cycle.
        Asynchronous 'work' is an explicit aspect of the NSI protocol.

    """

    registry: ClassVar[List[Type[Job]]] = []

    @classmethod
    def __init_subclass__(cls: Type[Job]) -> None:
        """Register sub classes for job recovery purposes."""
        super().__init_subclass__()
        cls.registry.append(cls)

    @abstractmethod
    def __call__(self) -> None:
        """Perform the work represented by this class.

        Sub classes must override this method.
        This method is called by the scheduler when the job is scheduled to run.
        """
        pass

    @classmethod
    @abstractmethod
    def recover(cls) -> List[Job]:
        """Recover work that did not run to completion due to a premature termination of SuPA.

        When SuPA needs to be terminated,
        there might still be some scheduled jobs that haven't yet run.
        These jobs might be recovered when SuPA's is started again.
        If they can, it is up to this class method to recreated these jobs.

        This is an abstract method as we want subclasses to be explict about their recovery process.

        See Also: :func:`supa.init_app`

        Returns:
            A list of instantiated jobs to be rescheduled.
        """
        return []

    @abstractmethod
    def trigger(self) -> DateTrigger:
        """Trigger for recovered jobs.

        Recovered jobs generally know when they should be run.
        This function provides the means to tell the recovery process exactly that.

        This is an abstract method as we want subclasses to be explicit about their trigger behaviour.

        Whatever this :meth:`trigger` function returns,
        is passed to the scheduler's
        `add_job() <https://apscheduler.readthedocs.io/en/latest/modules/schedulers/base.html#apscheduler.schedulers.base.BaseScheduler.add_job>`_
        method after the job has been passed into it.

        Example::

            from datetime import datetime, timezone
            from apscheduler.triggers.date import DateTrigger

            my_job = MyJob(...)
            my_job.trigger()  # -> DateTrigger(run_date=datetime(2020, 10, 8, 10, 0, tzinfo=timezone.utc))

            # Then the recovery process will do this:

            scheduler.add_job(my_job, my_job.trigger())

        If a job needs to be run immediately after recovery,
        then simply return DateTrigger(run_date=None).

        Returns:
            Tuple of arguments to be supplied to the ``add_job`` scheduler method.
        """  # noqa: E501 B950
        return DateTrigger(run_date=None)


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
        """Initialize NsiException.

        See instance attribute documentation for what the parameters are.
        """
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
        """Return the exception in a human readable format."""
        return self.text
