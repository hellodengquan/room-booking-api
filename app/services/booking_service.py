import uuid
from datetime import datetime, timedelta
from typing import List, Optional, Tuple, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, not_

from app.models.models import (
    Booking,
    Room,
    Device,
    BookingDevice,
    BookingStatus,
    RecurrenceType,
    PermissionLevel,
    RoomPermission,
)
from app.schemas.schemas import (
    BookingCreate,
    ConflictInfo,
    AlternativeSuggestion,
    RecurrenceConfig,
)
from app.config import settings


def check_time_conflict(
    db: Session,
    room_id: int,
    start_time: datetime,
    end_time: datetime,
    exclude_booking_id: Optional[int] = None,
    exclude_series_id: Optional[str] = None,
) -> List[ConflictInfo]:
    conflicts = []

    query = db.query(Booking).filter(
        Booking.room_id == room_id,
        Booking.status == BookingStatus.CONFIRMED,
        not_(
            or_(
                Booking.end_time <= start_time,
                Booking.start_time >= end_time,
            )
        ),
    )

    if exclude_booking_id:
        query = query.filter(Booking.id != exclude_booking_id)

    if exclude_series_id:
        query = query.filter(
            or_(Booking.series_id.is_(None), Booking.series_id != exclude_series_id)
        )

    conflicting_bookings = query.all()

    for cb in conflicting_bookings:
        conflict_type = "full_overlap"
        if cb.start_time < start_time and cb.end_time > end_time:
            conflict_type = "contains"
        elif start_time < cb.start_time and end_time > cb.end_time:
            conflict_type = "contained"
        elif start_time < cb.start_time < end_time:
            conflict_type = "overlap_start"
        elif start_time < cb.end_time < end_time:
            conflict_type = "overlap_end"

        conflicts.append(
            ConflictInfo(
                booking_id=cb.id,
                title=cb.title,
                start_time=cb.start_time,
                end_time=cb.end_time,
                user_id=cb.user_id,
                conflict_type=conflict_type,
            )
        )

    return conflicts


def check_device_conflict(
    db: Session,
    device_ids: List[int],
    start_time: datetime,
    end_time: datetime,
    exclude_booking_id: Optional[int] = None,
) -> List[ConflictInfo]:
    conflicts = []

    if not device_ids:
        return conflicts

    for device_id in device_ids:
        query = (
            db.query(Booking)
            .join(BookingDevice)
            .filter(
                BookingDevice.device_id == device_id,
                Booking.status == BookingStatus.CONFIRMED,
                not_(
                    or_(
                        Booking.end_time <= start_time,
                        Booking.start_time >= end_time,
                    )
                ),
            )
        )

        if exclude_booking_id:
            query = query.filter(Booking.id != exclude_booking_id)

        conflicting_bookings = query.all()

        for cb in conflicting_bookings:
            device = db.query(Device).filter(Device.id == device_id).first()
            conflicts.append(
                ConflictInfo(
                    booking_id=cb.id,
                    title=f"设备冲突: {device.name if device else '未知设备'}",
                    start_time=cb.start_time,
                    end_time=cb.end_time,
                    user_id=cb.user_id,
                    conflict_type="device_conflict",
                )
            )

    return conflicts


def generate_recurrence_dates(
    start_time: datetime,
    end_time: datetime,
    recurrence_config: RecurrenceConfig,
) -> List[Tuple[datetime, datetime]]:
    dates = []
    duration = end_time - start_time

    if recurrence_config.recurrence_type == RecurrenceType.NONE:
        return [(start_time, end_time)]

    recurrence_end_date = recurrence_config.recurrence_end_date
    if not recurrence_end_date:
        recurrence_end_date = start_time + timedelta(days=settings.MAX_RECURRENCE_DAYS)

    interval = recurrence_config.recurrence_interval or 1
    current_date = start_time.date()
    end_date_limit = recurrence_end_date.date()

    weekdays = recurrence_config.recurrence_weekdays

    while current_date <= end_date_limit:
        if recurrence_config.recurrence_type == RecurrenceType.DAILY:
            if current_date >= start_time.date():
                new_start = datetime.combine(current_date, start_time.time())
                new_end = new_start + duration
                dates.append((new_start, new_end))
            current_date += timedelta(days=interval)

        elif recurrence_config.recurrence_type in [
            RecurrenceType.WEEKLY,
            RecurrenceType.BIWEEKLY,
        ]:
            week_interval = interval if recurrence_config.recurrence_type == RecurrenceType.WEEKLY else interval * 2

            if current_date >= start_time.date():
                if weekdays:
                    for day_offset in range(7):
                        weekday_date = current_date + timedelta(days=day_offset)
                        if (
                            weekday_date.weekday() in weekdays
                            and weekday_date <= end_date_limit
                            and weekday_date >= start_time.date()
                        ):
                            new_start = datetime.combine(weekday_date, start_time.time())
                            new_end = new_start + duration
                            dates.append((new_start, new_end))
                else:
                    if current_date.weekday() == start_time.weekday():
                        new_start = datetime.combine(current_date, start_time.time())
                        new_end = new_start + duration
                        dates.append((new_start, new_end))

            current_date += timedelta(weeks=week_interval)

        elif recurrence_config.recurrence_type == RecurrenceType.MONTHLY:
            if current_date >= start_time.date():
                if current_date.day == start_time.day:
                    new_start = datetime.combine(current_date, start_time.time())
                    new_end = new_start + duration
                    dates.append((new_start, new_end))

            if current_date.month == 12:
                current_date = current_date.replace(
                    year=current_date.year + interval, month=1
                )
            else:
                current_date = current_date.replace(
                    month=current_date.month + interval
                )

    return dates


def find_alternative_slots(
    db: Session,
    room_id: int,
    desired_start: datetime,
    desired_end: datetime,
    exclude_booking_id: Optional[int] = None,
    max_suggestions: int = settings.MAX_ALTERNATIVE_SUGGESTIONS,
) -> List[AlternativeSuggestion]:
    suggestions = []
    duration = desired_end - desired_start
    duration_minutes = int(duration.total_seconds() / 60)

    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        return suggestions

    existing_bookings = (
        db.query(Booking)
        .filter(
            Booking.room_id == room_id,
            Booking.status == BookingStatus.CONFIRMED,
            Booking.start_time >= desired_start - timedelta(days=7),
            Booking.end_time <= desired_end + timedelta(days=7),
        )
        .order_by(Booking.start_time)
        .all()
    )

    if exclude_booking_id:
        existing_bookings = [b for b in existing_bookings if b.id != exclude_booking_id]

    candidate_periods = [
        (desired_start, desired_end),
        (desired_start + timedelta(minutes=30), desired_end + timedelta(minutes=30)),
        (desired_start - timedelta(minutes=30), desired_end - timedelta(minutes=30)),
        (desired_start + timedelta(hours=1), desired_end + timedelta(hours=1)),
        (desired_start - timedelta(hours=1), desired_end - timedelta(hours=1)),
        (desired_start + timedelta(days=1), desired_end + timedelta(days=1)),
        (desired_start - timedelta(days=1), desired_end - timedelta(days=1)),
    ]

    all_rooms = db.query(Room).filter(Room.is_active == True).all()

    for room_candidate in all_rooms:
        for start, end in candidate_periods:
            if start < datetime.now():
                continue

            if room_candidate.id == room_id:
                conflicts = check_time_conflict(
                    db, room_candidate.id, start, end, exclude_booking_id
                )
            else:
                conflicts = check_time_conflict(db, room_candidate.id, start, end)

            if not conflicts:
                suggestions.append(
                    AlternativeSuggestion(
                        room_id=room_candidate.id,
                        room_name=room_candidate.name,
                        start_time=start,
                        end_time=end,
                        duration_minutes=duration_minutes,
                    )
                )

                if len(suggestions) >= max_suggestions:
                    return suggestions

    return suggestions


def check_user_permission(
    db: Session, user_id: int, room_id: int, required_level: PermissionLevel
) -> bool:
    from app.models.models import User

    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.is_active:
        return False

    if user.permission_level == PermissionLevel.ADMIN:
        return True

    if required_level == PermissionLevel.VIEW:
        return True

    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        return False

    room_permission = (
        db.query(RoomPermission)
        .filter(
            RoomPermission.room_id == room_id,
            RoomPermission.user_id == user_id,
        )
        .first()
    )

    if room_permission:
        if required_level == PermissionLevel.BOOK:
            return room_permission.permission_level in [
                PermissionLevel.BOOK,
                PermissionLevel.ADMIN,
            ]
        elif required_level == PermissionLevel.ADMIN:
            return room_permission.permission_level == PermissionLevel.ADMIN

    if room.requires_approval and required_level == PermissionLevel.BOOK:
        return False

    return user.permission_level == PermissionLevel.BOOK


def create_booking_with_devices(
    db: Session,
    booking_data: BookingCreate,
    user_id: int,
    start_time: datetime,
    end_time: datetime,
    series_id: Optional[str] = None,
) -> Booking:
    status = BookingStatus.CONFIRMED
    room = db.query(Room).filter(Room.id == booking_data.room_id).first()
    if room and room.requires_approval:
        status = BookingStatus.PENDING

    recurrence_type = RecurrenceType.NONE
    recurrence_end_date = None
    recurrence_weekdays = None
    recurrence_interval = 1

    if booking_data.recurrence:
        recurrence_type = booking_data.recurrence.recurrence_type
        recurrence_end_date = booking_data.recurrence.recurrence_end_date
        recurrence_weekdays = booking_data.recurrence.recurrence_weekdays
        recurrence_interval = booking_data.recurrence.recurrence_interval

    db_booking = Booking(
        room_id=booking_data.room_id,
        user_id=user_id,
        title=booking_data.title,
        description=booking_data.description,
        start_time=start_time,
        end_time=end_time,
        status=status,
        recurrence_type=recurrence_type,
        recurrence_end_date=recurrence_end_date,
        recurrence_weekdays=recurrence_weekdays,
        recurrence_interval=recurrence_interval,
        series_id=series_id,
        attendee_count=booking_data.attendee_count,
    )
    db.add(db_booking)
    db.flush()

    if booking_data.device_ids:
        for device_id in booking_data.device_ids:
            device = db.query(Device).filter(Device.id == device_id).first()
            if device and device.is_available:
                booking_device = BookingDevice(
                    booking_id=db_booking.id,
                    device_id=device_id,
                )
                db.add(booking_device)

    return db_booking


def create_recurring_bookings(
    db: Session,
    booking_data: BookingCreate,
    user_id: int,
) -> Tuple[List[Booking], List[Dict[str, Any]]]:
    created_bookings = []
    errors = []

    series_id = str(uuid.uuid4())

    if not booking_data.recurrence:
        dates = [(booking_data.start_time, booking_data.end_time)]
    else:
        dates = generate_recurrence_dates(
            booking_data.start_time,
            booking_data.end_time,
            booking_data.recurrence,
        )

    for idx, (start, end) in enumerate(dates):
        try:
            time_conflicts = check_time_conflict(db, booking_data.room_id, start, end)
            device_conflicts = []
            if booking_data.device_ids:
                device_conflicts = check_device_conflict(
                    db, booking_data.device_ids, start, end
                )

            all_conflicts = time_conflicts + device_conflicts

            if all_conflicts and idx == 0:
                errors.append(
                    {
                        "start_time": start,
                        "end_time": end,
                        "errors": [
                            f"时间冲突: {c.title}" for c in all_conflicts
                        ],
                    }
                )
                continue

            if all_conflicts:
                errors.append(
                    {
                        "start_time": start,
                        "end_time": end,
                        "errors": [
                            f"时间冲突: {c.title}" for c in all_conflicts
                        ],
                    }
                )
                continue

            booking = create_booking_with_devices(
                db, booking_data, user_id, start, end, series_id
            )
            created_bookings.append(booking)

        except Exception as e:
            errors.append(
                {
                    "start_time": start,
                    "end_time": end,
                    "errors": [str(e)],
                }
            )

    db.commit()
    return created_bookings, errors
