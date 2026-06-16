from datetime import datetime
from enum import Enum as PyEnum
from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    Boolean,
    ForeignKey,
    Text,
    Enum,
    JSON,
    UniqueConstraint,
    Float,
)
from sqlalchemy.orm import relationship, declarative_base

Base = declarative_base()


class Weekday(PyEnum):
    MONDAY = 0
    TUESDAY = 1
    WEDNESDAY = 2
    THURSDAY = 3
    FRIDAY = 4
    SATURDAY = 5
    SUNDAY = 6


class RecurrenceType(PyEnum):
    NONE = "none"
    DAILY = "daily"
    WEEKLY = "weekly"
    BIWEEKLY = "biweekly"
    MONTHLY = "monthly"


class BookingStatus(PyEnum):
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    PENDING = "pending"
    SKIPPED = "skipped"


class PermissionLevel(PyEnum):
    VIEW = "view"
    BOOK = "book"
    ADMIN = "admin"


class CancellationRequestStatus(PyEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    ROLLBACK = "rollback"


class SuggestionScoreLevel(PyEnum):
    EXCELLENT = "excellent"
    GOOD = "good"
    FAIR = "fair"
    POOR = "poor"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    email = Column(String(100), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(100))
    is_active = Column(Boolean, default=True)
    permission_level = Column(
        Enum(PermissionLevel), default=PermissionLevel.BOOK, nullable=False
    )
    timezone = Column(String(50), default="Asia/Shanghai")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    bookings = relationship("Booking", back_populates="user")
    room_permissions = relationship("RoomPermission", back_populates="user")
    delegations_from = relationship(
        "BookingDelegation",
        foreign_keys="BookingDelegation.delegator_id",
        back_populates="delegator",
    )
    delegations_to = relationship(
        "BookingDelegation",
        foreign_keys="BookingDelegation.delegate_id",
        back_populates="delegate",
    )
    cancellation_requests = relationship(
        "CancellationRequest",
        foreign_keys="CancellationRequest.requester_id",
        back_populates="requester",
    )


class Device(Base):
    __tablename__ = "devices"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    device_type = Column(String(50), nullable=False)
    description = Column(Text)
    is_available = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    room_devices = relationship("RoomDevice", back_populates="device")
    booking_devices = relationship("BookingDevice", back_populates="device")


class Room(Base):
    __tablename__ = "rooms"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, index=True)
    location = Column(String(200))
    capacity = Column(Integer, nullable=False)
    description = Column(Text)
    is_active = Column(Boolean, default=True)
    requires_approval = Column(Boolean, default=False)
    min_booking_duration = Column(Integer, default=30)
    max_booking_duration = Column(Integer, default=480)
    timezone = Column(String(50), default="Asia/Shanghai")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    bookings = relationship("Booking", back_populates="room")
    room_devices = relationship("RoomDevice", back_populates="room")
    room_permissions = relationship("RoomPermission", back_populates="room")


class RoomDevice(Base):
    __tablename__ = "room_devices"

    id = Column(Integer, primary_key=True, index=True)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=False)
    device_id = Column(Integer, ForeignKey("devices.id"), nullable=False)
    is_permanent = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    room = relationship("Room", back_populates="room_devices")
    device = relationship("Device", back_populates="room_devices")

    __table_args__ = (
        UniqueConstraint("room_id", "device_id", name="uq_room_device"),
    )


class RoomPermission(Base):
    __tablename__ = "room_permissions"

    id = Column(Integer, primary_key=True, index=True)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    permission_level = Column(
        Enum(PermissionLevel), default=PermissionLevel.VIEW, nullable=False
    )
    created_at = Column(DateTime, default=datetime.utcnow)

    room = relationship("Room", back_populates="room_permissions")
    user = relationship("User", back_populates="room_permissions")

    __table_args__ = (
        UniqueConstraint("room_id", "user_id", name="uq_room_permission"),
    )


class Booking(Base):
    __tablename__ = "bookings"

    id = Column(Integer, primary_key=True, index=True)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    title = Column(String(200), nullable=False)
    description = Column(Text)
    start_time = Column(DateTime, nullable=False, index=True)
    end_time = Column(DateTime, nullable=False, index=True)
    status = Column(
        Enum(BookingStatus), default=BookingStatus.CONFIRMED, nullable=False
    )
    recurrence_type = Column(
        Enum(RecurrenceType), default=RecurrenceType.NONE, nullable=False
    )
    recurrence_end_date = Column(DateTime)
    recurrence_weekdays = Column(JSON)
    recurrence_interval = Column(Integer, default=1)
    series_id = Column(String(100), index=True)
    attendee_count = Column(Integer, default=1)
    original_booking_id = Column(Integer, ForeignKey("bookings.id"))
    delegation_id = Column(Integer, ForeignKey("booking_delegations.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    room = relationship("Room", back_populates="bookings")
    user = relationship("User", back_populates="bookings")
    booking_devices = relationship("BookingDevice", back_populates="booking")
    skips = relationship("BookingSkip", back_populates="booking")
    delegation = relationship("BookingDelegation", back_populates="bookings")


class BookingDevice(Base):
    __tablename__ = "booking_devices"

    id = Column(Integer, primary_key=True, index=True)
    booking_id = Column(Integer, ForeignKey("bookings.id"), nullable=False)
    device_id = Column(Integer, ForeignKey("devices.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    booking = relationship("Booking", back_populates="booking_devices")
    device = relationship("Device", back_populates="booking_devices")

    __table_args__ = (
        UniqueConstraint("booking_id", "device_id", name="uq_booking_device"),
    )


class BookingSkip(Base):
    __tablename__ = "booking_skips"

    id = Column(Integer, primary_key=True, index=True)
    booking_id = Column(Integer, ForeignKey("bookings.id"), nullable=False)
    series_id = Column(String(100), index=True)
    skip_date = Column(DateTime, nullable=False)
    reason = Column(Text)
    skipped_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)

    booking = relationship("Booking", back_populates="skips")


class BookingDelegation(Base):
    __tablename__ = "booking_delegations"

    id = Column(Integer, primary_key=True, index=True)
    delegator_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    delegate_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    room_id = Column(Integer, ForeignKey("rooms.id"))
    is_active = Column(Boolean, default=True)
    start_date = Column(DateTime)
    end_date = Column(DateTime)
    reason = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    delegator = relationship(
        "User", foreign_keys=[delegator_id], back_populates="delegations_from"
    )
    delegate = relationship(
        "User", foreign_keys=[delegate_id], back_populates="delegations_to"
    )
    bookings = relationship("Booking", back_populates="delegation")


class CancellationRequest(Base):
    __tablename__ = "cancellation_requests"

    id = Column(Integer, primary_key=True, index=True)
    requester_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    approver_id = Column(Integer, ForeignKey("users.id"))
    status = Column(
        Enum(CancellationRequestStatus),
        default=CancellationRequestStatus.PENDING,
        nullable=False,
    )
    reason = Column(Text)
    approval_reason = Column(Text)
    booking_ids = Column(JSON, nullable=False)
    cancellation_type = Column(String(50), default="ids")
    params = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)
    approved_at = Column(DateTime)
    rolled_back_at = Column(DateTime)

    requester = relationship(
        "User", foreign_keys=[requester_id], back_populates="cancellation_requests"
    )
    audit_logs = relationship("CancellationAuditLog", back_populates="request")


class CancellationAuditLog(Base):
    __tablename__ = "cancellation_audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    request_id = Column(Integer, ForeignKey("cancellation_requests.id"), nullable=False)
    booking_id = Column(Integer, ForeignKey("bookings.id"), nullable=False)
    original_status = Column(Enum(BookingStatus), nullable=False)
    new_status = Column(Enum(BookingStatus), nullable=False)
    action_type = Column(String(50), nullable=False)
    action_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)

    request = relationship("CancellationRequest", back_populates="audit_logs")
