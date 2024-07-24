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
"""Define the database models.

Surrogate keys versus natural keys
==================================

Looking at the model definitions
you'll find that we have used `natural keys <https://en.wikipedia.org/wiki/Natural_key>`_ wherever possible.
Though no too common these days,
with the prevalent use of ORMs
that automatically generate a `surrogate key <https://en.wikipedia.org/wiki/Surrogate_key>`_ per model,
SQLAlchemy is flexible enough to model things 'naturally' from a relational database point of view.
This sometimes results in `composite <https://en.wikipedia.org/wiki/Compound_key>`_ primary keys.

Foreign keys to these composite primary keys cannot be defined on a specific Column definition
or even a set of Column definitions.
Something that does work for composite primary key definitions.
Instead,
these foreign keys need to be defined using a
`ForeignKeyConstraint <https://docs.sqlalchemy.org/en/13/core/constraints.html?sqlalchemy.schema.ForeignKeyConstraint#sqlalchemy.schema.ForeignKeyConstraint>`_
on the ``__table_args__`` attribute of the DB model.

Connection IDs
==============

Looking at example messages in the different specifications:

* `GFD-R-233 Applying Policy in the NSI Environment (pdf) <https://www.ogf.org/documents/GFD.233.pdf>`_
* `GWD-R-P.237 NSI Connection Service v2.1 (pdf) <https://www.ogf.org/documents/GFD.237.pdf>`_

we see that connection IDs always seem to be formatted as ``UUID``'s.
However, according to its definition in GWD-R-P.237,
it can be any string as long as it is unique within the context of a PA.
That is the reason that we have modelled connection IDs from other NSA's
(``ag_connection_id``, ``upa_connection_id``)
as ``TEXT``.
Within SuPA we have decided to use ``UUID``'s for our ``connection_id``'s.


SQLAlchemy Model Dependency Diagram
===================================

A visual representation of how everything is wired together
should help navigating the Python code a lot better.

.. image:: /images/sqlalchemy_model_dependency_diagram.png


"""  # noqa: E501 B950
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import (
    CheckConstraint,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    TypeDecorator,
    UniqueConstraint,
    inspect,
)
from sqlalchemy.dialects import sqlite
from sqlalchemy.engine import Dialect
from sqlalchemy.exc import DontWrapMixin
from sqlalchemy.ext.orderinglist import ordering_list
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, object_session, relationship

from supa.connection.fsm import (
    DataPlaneStateMachine,
    LifecycleStateMachine,
    ProvisionStateMachine,
    ReservationStateMachine,
)
from supa.util import nsi
from supa.util.timestamp import NO_END_DATE, current_timestamp
from supa.util.type import NotificationType, RequestType, ResultType


class Uuid(TypeDecorator):
    """Implement SQLAlchemy Uuid column type for SQLite databases.

    This stores Python :class:`uuid.UUID` types as strings (``CHAR(36)``) in the database.
    We have chosen to store the :meth:`uuid.UUID.__str__` representation directly,
    eg. with ``"-"`` between the UUID fields,
    for improved readability.
    """

    impl = sqlite.CHAR(36)

    cache_ok = True

    def process_bind_param(self, value: Optional[uuid.UUID], dialect: Dialect) -> Optional[str]:  # noqa: D102
        if value is not None:
            if not isinstance(value, uuid.UUID):
                raise ValueError(f"{value} is not a valid UUID.")
            return str(value)
        return value

    def process_result_value(self, value: Optional[str], dialect: Dialect) -> Optional[uuid.UUID]:  # noqa: D102
        if value is None:
            return value
        return uuid.UUID(value)


class ReprBase:
    """Custom SQLAlchemy model to provide meaningful :meth:`__str__` and :meth:`__repr__` methods.

    Writing appropriate ``__repr__`` and ``__str__`` methods
    for all your SQLAlchemy ORM models
    gets tedious very quickly.
    By using SQLAlchemy's
    `Runtime Inspection API
    <https://docs.sqlalchemy.org/en/latest/core/inspection.html?highlight=runtime inspection api>`_
    this base class can easily generate these methods for you.

    .. note:: This class cannot be used as a regular Python base class
              due to assumptions made by ``declarative_base``. See **Usage** below instead.

    Usage::

        Base = declarative_base(cls=ReprBase)
    """

    def __repr__(self) -> str:
        """Return string that represents a SQLAlchemy ORM model."""
        inst_state = inspect(self)
        attr_vals = [
            f"{attr.key}={getattr(self, attr.key)}"
            for attr in inst_state.mapper.column_attrs  # type: ignore[union-attr]
        ]
        return f"{self.__class__.__name__}({', '.join(attr_vals)})"

    def __str__(self) -> str:
        """Return string that represents a SQLAlchemy ORM model."""
        return self.__repr__()


class UtcTimestampException(Exception, DontWrapMixin):
    """Exception class for custom UtcTimestamp SQLAlchemy column type."""

    pass


class UtcTimestamp(TypeDecorator):
    """Custom SQLAlchemy column type for storing timestamps in UTC in SQLite databases.

    This column type always returns timestamps with the UTC timezone.
    It also guards against accidentally trying to store Python naive timestamps
    (those without a time zone).

    In the SQLite database the timestamps are stored as strings of format: ``yyyy-mm-dd hh:mm:ss``.
    **UTC is always implied.**
    """

    impl = sqlite.DATETIME(truncate_microseconds=False)

    cache_ok = True

    def process_bind_param(self, value: Optional[datetime], dialect: Dialect) -> Optional[datetime]:  # noqa: D102
        if value is not None:
            if value.tzinfo is None:
                raise UtcTimestampException(f"Expected timestamp with tzinfo. Got naive timestamp {value!r} instead")
            return value.astimezone(timezone.utc)
        return value

    def process_result_value(self, value: Optional[datetime], dialect: Dialect) -> Optional[datetime]:  # noqa: D102
        if value is not None:
            if value.tzinfo is not None:
                return value.astimezone(timezone.utc)
            return value.replace(tzinfo=timezone.utc)
        return value


class Base(ReprBase, DeclarativeBase):
    """Base class used for declarative class definitions."""

    type_annotation_map = {
        uuid.UUID: Uuid(),
        datetime: UtcTimestamp(),
    }


class Reservation(Base):
    """DB mapping for registering NSI reservations."""

    __tablename__ = "reservations"

    # Most of these attribute come from different parts of the ``ReserveRequest`` message.
    # Although this is not a direct mapping, we have indicated from what parts some these
    # attribute comes from.

    connection_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    version: Mapped[int]
    # header
    protocol_version: Mapped[str]
    requester_nsa: Mapped[str]
    provider_nsa: Mapped[str]
    reply_to: Mapped[Optional[str]]
    session_security_attributes: Mapped[Optional[str]]

    @property
    def correlation_id(self) -> uuid.UUID:
        """Return correlation_id of the latest request for this connection_id."""
        session = object_session(self)
        result: List[Tuple[uuid.UUID]] = (
            session.query(Request.correlation_id)  # type: ignore
            .filter(Request.connection_id == self.connection_id)
            .order_by(Request.timestamp)
            .all()
        )
        return result[-1][0]

    # request message (+ connection_id)
    global_reservation_id: Mapped[str]
    description: Mapped[Optional[str]]

    # internal state keeping
    reservation_state = mapped_column(
        Enum(*[s.value for s in ReservationStateMachine.states]),
        nullable=False,
        default=ReservationStateMachine.ReserveStart.value,
    )
    provision_state = mapped_column(Enum(*[s.value for s in ProvisionStateMachine.states]))
    lifecycle_state = mapped_column(
        Enum(*[s.value for s in LifecycleStateMachine.states]),
        nullable=False,
        default=LifecycleStateMachine.Created.value,
    )
    data_plane_state = mapped_column(Enum(*[s.value for s in DataPlaneStateMachine.states]))
    # need this because the reservation state machine is missing a state
    reservation_timeout: Mapped[bool] = mapped_column(default=False)

    # some housekeeping, last_modified is used by the Query lastModifiedSince
    create_date: Mapped[datetime] = mapped_column(default=current_timestamp)
    last_modified: Mapped[Optional[datetime]] = mapped_column(onupdate=current_timestamp, index=True)

    # another header part
    path_trace = relationship(
        "PathTrace",
        uselist=False,
        back_populates="reservation",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )  # one-to-one

    parameters = relationship(
        "Parameter",
        backref="reservation",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    connection = relationship(
        "Connection",
        uselist=False,
        back_populates="reservation",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )  # one-to-one

    schedules = relationship(
        "Schedule",
        order_by="asc(Schedule.version)",
        back_populates="reservation",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    schedule = relationship(
        "Schedule",
        uselist=False,
        primaryjoin="""and_(
                            Reservation.connection_id==Schedule.connection_id,
                            Reservation.version==Schedule.version
                        )""",
        viewonly=True,
    )

    p2p_criteria_list = relationship(
        "P2PCriteria",
        order_by="asc(P2PCriteria.version)",
        back_populates="reservation",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    p2p_criteria = relationship(
        "P2PCriteria",
        uselist=False,
        primaryjoin="""and_(
                            Reservation.connection_id==P2PCriteria.connection_id,
                            Reservation.version==P2PCriteria.version
                        )""",
        viewonly=True,
    )

    notification = relationship(
        "Notification",
        back_populates="reservation",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    result = relationship(
        "Result",
        back_populates="reservation",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Schedule(Base):
    """DB mapping for versioned schedules."""

    __tablename__ = "schedules"

    schedule_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    connection_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(Reservation.connection_id))
    version: Mapped[int] = mapped_column()
    UniqueConstraint(connection_id, version)

    # schedule
    start_time: Mapped[datetime] = mapped_column(default=current_timestamp, index=True)
    end_time: Mapped[datetime] = mapped_column(default=NO_END_DATE, index=True)
    __table_args__ = (CheckConstraint(start_time < end_time),)

    reservation = relationship(
        Reservation,
        back_populates="schedules",
    )  # (cascades defined in parent)


class P2PCriteria(Base):
    """DB mapping for versioned P2P criteria."""

    __tablename__ = "p2p_criteria"

    p2p_criteria_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    connection_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(Reservation.connection_id))
    version: Mapped[int] = mapped_column()
    UniqueConstraint(connection_id, version)

    # p2p criteria
    bandwidth: Mapped[int] = mapped_column(comment="Mbps")
    directionality = mapped_column(Enum("BI_DIRECTIONAL", "UNI_DIRECTIONAL"), nullable=False, default="BI_DIRECTIONAL")
    symmetric: Mapped[bool]

    src_domain: Mapped[str]
    src_topology: Mapped[str]
    src_stp_id: Mapped[str] = mapped_column(comment="uniq identifier of STP in the topology")
    src_vlans: Mapped[str]
    # `src_vlans` might be a range of VLANs in case the reservation specified an unqualified STP.
    # In that case it is up to the reservation process to select an available VLAN out of the
    # supplied range.
    # This also explain the difference in column types. A range is expressed as a string (eg "1-10").
    # A single VLAN is always a single number, hence integer.
    src_selected_vlan: Mapped[Optional[int]]
    dst_domain: Mapped[str]
    dst_topology: Mapped[str]
    dst_stp_id: Mapped[str] = mapped_column(comment="uniq identifier of STP in the topology")
    dst_vlans: Mapped[str]
    # See `src_selected_vlan`
    dst_selected_vlan: Mapped[Optional[int]]

    reservation = relationship(
        Reservation,
        back_populates="p2p_criteria_list",
    )  # (cascades defined in parent)

    def src_stp(self, selected: bool = False) -> nsi.Stp:
        """Return :class:`~supa.util.nsi.STP` instance for src data.

        Depending on where we are in the reservation process,
        we need to deal with a requested VLAN(s)(ranges),
        or a selected VLAN.
        The ``selected`` parameter determines which of the two
        will be used for the ``labels`` argument to the :class:`~supa.util.nsi.Stp` object.

        Args:
            selected: if True, use 'selected VLAN` instead of requested VLAN(s)(ranges)

        Returns:
            :class:`~supa.util.nsi.Stp` object
        """
        vlans = self.src_selected_vlan if selected else self.src_vlans
        labels = f"vlan={vlans}"
        return nsi.Stp(self.src_domain, self.src_topology, self.src_stp_id, labels)

    def dst_stp(self, selected: bool = False) -> nsi.Stp:
        """Return :class:`~supa.util.nsi.STP` instance for dst data.

        Depending on where we are in the reservation process,
        we need to deal with a requested VLAN(s)(ranges),
        or a selected VLAN.
        The ``selected`` parameter determines which of the two
        will be used for the ``labels`` argument to the :class:`~supa.util.nsi.Stp` object.

        Args:
            selected: if True, use 'selected VLAN` instead of requested VLAN(s)(ranges)

        Returns:
            :class:`~supa.util.nsi.Stp` object
        """
        vlans = self.dst_selected_vlan if selected else self.dst_vlans
        labels = f"vlan={vlans}"
        return nsi.Stp(self.dst_domain, self.dst_topology, self.dst_stp_id, labels)


class PathTrace(Base):
    """DB mapping for PathTraces."""

    __tablename__ = "path_traces"

    path_trace_id: Mapped[str] = mapped_column(
        primary_key=True, comment="NSA identifier of root or head-end aggregator NSA"
    )
    ag_connection_id: Mapped[str] = mapped_column(primary_key=True, comment="Aggregator issued connection_id")

    connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(Reservation.connection_id, ondelete="CASCADE"), comment="Our connection_id"
    )

    reservation = relationship(
        Reservation,
        back_populates="path_trace",
    )  # one-to-one (cascades defined in parent)

    paths = relationship(
        "Path",
        backref="path_trace",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        # Ensure that the column used in joins with the parent table will have an index.
        Index("fx_to_reservations_idx", connection_id),
    )


class Path(Base):
    """DB mapping for Paths."""

    __tablename__ = "paths"

    path_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # need to assign something in order to use this field in the table args below
    path_trace_id: Mapped[str] = mapped_column()
    ag_connection_id: Mapped[str] = mapped_column()

    segments = relationship(
        "Segment",
        backref="path",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Segment.order",
        collection_class=ordering_list("order"),
    )

    __table_args__ = (
        ForeignKeyConstraint(
            (path_trace_id, ag_connection_id), (PathTrace.path_trace_id, PathTrace.ag_connection_id), ondelete="CASCADE"
        ),
        # Ensure that columns used in joins with the parent table will have an index.
        Index("fk_to_path_traces_idx", path_trace_id, ag_connection_id),
    )


class Segment(Base):
    """DB mapping for Segment."""

    __tablename__ = "segments"

    segment_id: Mapped[str] = mapped_column(
        primary_key=True, comment="The NSA identifier for the uPA associated with this path segment"
    )
    path_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(Path.path_id, ondelete="CASCADE"), primary_key=True)

    upa_connection_id: Mapped[str] = mapped_column(comment="Not ours; it's is the connection_id from another uPA")
    order: Mapped[int] = mapped_column()

    stps = relationship(
        "Stp",
        backref="segment",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Stp.order",
        collection_class=ordering_list("order"),
    )

    # By virtue of the composite unique constraint,
    # a composite index will be created with the first column being `path_id`.
    # This index can be for joins involving the foreign key column.
    # Hence no need to create a separate index
    __table_args__ = (UniqueConstraint(path_id, order),)


class Stp(Base):
    """DB Mapping for STP."""

    __tablename__ = "stps"

    stp_id: Mapped[str] = mapped_column(primary_key=True, comment="Assumes fully qualified STP")
    segment_id: Mapped[str] = mapped_column()
    path_id: Mapped[uuid.UUID] = mapped_column()
    order: Mapped[int] = mapped_column()

    __table_args__ = (
        ForeignKeyConstraint((segment_id, path_id), (Segment.segment_id, Segment.path_id), ondelete="CASCADE"),
        UniqueConstraint(segment_id, order),
        # Ensure that columns used in joins with the parent table will have an index.
        Index("fk_to_segment_idx", segment_id, path_id),
    )


class Parameter(Base):
    """DB mapping for PointToPointService Parameters."""

    __tablename__ = "parameters"

    connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(Reservation.connection_id, ondelete="CASCADE"), primary_key=True
    )
    key: Mapped[str] = mapped_column(primary_key=True)
    value: Mapped[Optional[str]]


class Topology(Base):
    """DB mapping for STP's and ports in the topology from the NRM."""

    __tablename__ = "topology"

    stp_id: Mapped[str] = mapped_column(primary_key=True, index=True)
    port_id: Mapped[str] = mapped_column(comment="NRM port identifier")
    vlans: Mapped[str]
    bandwidth: Mapped[int] = mapped_column(comment="Mbps")
    description: Mapped[Optional[str]]
    is_alias_in: Mapped[Optional[str]]
    is_alias_out: Mapped[Optional[str]]

    # A STP might still be in operation (eg active) as part of one or more connections.
    # However to prevent new reservations be made against it,
    # we can enable or disable it.
    enabled: Mapped[bool] = mapped_column(default=True, comment="We don't delete STP's, we enable or disable them.")


class Connection(Base):
    """DB mapping for registering connections to be build/built.

    It stores references to the actual STP's used in the connection as listed in :class`Topology`
    and the ``circuit_id`` of the circuit in the NRM.
    """

    __tablename__ = "connections"

    connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(Reservation.connection_id, ondelete="CASCADE"), primary_key=True
    )
    bandwidth: Mapped[int] = mapped_column(comment="Mbps")

    # Mind the singular {src,dst}_vlan
    # compared to the plural {src,dst}_vlans in
    # :class:`Reservation`.
    # We use singular here,
    # as by the time we are creating a Connection a VLAN
    # per port will have been selected.
    src_port_id: Mapped[str] = mapped_column(comment="id of src port in NRM")
    src_vlan: Mapped[int]
    dst_port_id: Mapped[str] = mapped_column(comment="id of dst port in NRM")
    dst_vlan: Mapped[int]
    circuit_id: Mapped[Optional[str]] = mapped_column(unique=True, comment="id of circuit in the NRM")

    reservation = relationship(
        Reservation,
        back_populates="connection",
    )  # one-to-one (cascades defined in parent)


def connection_to_dict(connection: Connection) -> Dict[str, Any]:
    """Create a dict from a Connection.

    A convenience function to create a dict that can be used as parameter list to all backend methods.
    """
    return {column.name: getattr(connection, column.name) for column in connection.__table__.columns}


class Request(Base):
    """DB mapping for registering async RA to PA request messages.

    Store the async request from a requester agent to this provider agent.
    """

    __tablename__ = "requests"

    correlation_id: Mapped[uuid.UUID] = mapped_column(comment="urn:uid", primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(default=current_timestamp)
    connection_id: Mapped[Optional[uuid.UUID]]
    request_type = mapped_column(Enum(*[r_type.value for r_type in RequestType]), nullable=False)
    request_data: Mapped[bytes]


class Notification(Base):
    """DB mapping for registering notifications against a connection ID.

    Store the notification for a connection ID serialized to string together
    with a linearly increasing identifier that can be used for ordering notifications in
    the context of the connection ID.
    """

    __tablename__ = "notifications"

    connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(Reservation.connection_id, ondelete="CASCADE"), primary_key=True
    )
    timestamp: Mapped[datetime] = mapped_column(default=current_timestamp)
    notification_id: Mapped[int] = mapped_column(primary_key=True)
    notification_type = mapped_column(Enum(*[n_type.value for n_type in NotificationType]), nullable=False)
    notification_data: Mapped[bytes]

    reservation = relationship(
        Reservation,
        back_populates="notification",
    )  # (cascades defined in parent)


class Result(Base):
    """DB mapping for registering results against a connection ID.

    Store the async result to a provider request serialized to string together
    with a linearly increasing identifier that can be used for ordering results in
    the context of the connection ID. Results of requests from a RA to a PA
    are stored so they can be retrieved later in case only synchronous communication
    is possible between the RA and PA.
    """

    __tablename__ = "results"

    connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(Reservation.connection_id, ondelete="CASCADE"), primary_key=True
    )
    timestamp: Mapped[datetime] = mapped_column(default=current_timestamp)
    correlation_id: Mapped[uuid.UUID] = mapped_column(comment="urn:uid", unique=True)
    result_id: Mapped[int] = mapped_column(primary_key=True)
    result_type = mapped_column(Enum(*[r_type.value for r_type in ResultType]), nullable=False)
    result_data: Mapped[bytes]

    reservation = relationship(
        Reservation,
        back_populates="result",
    )  # (cascades defined in parent)
