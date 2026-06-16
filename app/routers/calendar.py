from datetime import datetime, timedelta
from typing import List, Optional, Dict
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import and_

from app.database import get_db
from app.dependencies import get_current_active_user
from app.models.models import (
    Booking,
    Room,
    BookingStatus,
    User,
    RoomDevice,
    Device,
)
from app.schemas.schemas import (
    CalendarViewResponse,
    CalendarBooking,
    RoomListResponse,
    AvailableSlotsResponse,
    AvailableSlot,
)
from app.services.booking_service import get_available_slots_with_devices
from app.config import settings

router = APIRouter(prefix="/calendar", tags=["日历视图"])


def _convert_timezone(dt: datetime, from_tz: str, to_tz: str) -> datetime:
    try:
        import pytz
        from_zone = pytz.timezone(from_tz)
        to_zone = pytz.timezone(to_tz)
        if dt.tzinfo is None:
            dt = from_zone.localize(dt)
        return dt.astimezone(to_zone).replace(tzinfo=None)
    except ImportError:
        return dt
    except Exception:
        return dt


@router.get("/view", response_model=CalendarViewResponse)
async def get_calendar_view(
    start_date: datetime,
    end_date: datetime,
    room_ids: Optional[List[int]] = Query(None),
    user_id: Optional[int] = None,
    timezone: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    if end_date <= start_date:
        raise HTTPException(status_code=400, detail="结束日期必须晚于开始日期")

    if (end_date - start_date).days > 365:
        raise HTTPException(status_code=400, detail="查询范围不能超过365天")

    target_timezone = timezone or current_user.timezone or settings.DEFAULT_TIMEZONE

    rooms_query = db.query(Room).filter(Room.is_active == True)
    if room_ids:
        rooms_query = rooms_query.filter(Room.id.in_(room_ids))
    rooms = rooms_query.all()

    if not rooms:
        raise HTTPException(status_code=404, detail="未找到符合条件的会议室")

    bookings_query = db.query(Booking).filter(
        and_(
            Booking.start_time <= end_date,
            Booking.end_time >= start_date,
            Booking.status != BookingStatus.CANCELLED,
            Booking.status != BookingStatus.SKIPPED,
        )
    )

    if room_ids:
        bookings_query = bookings_query.filter(Booking.room_id.in_(room_ids))

    if user_id:
        bookings_query = bookings_query.filter(Booking.user_id == user_id)

    bookings = bookings_query.order_by(Booking.start_time).all()

    calendar: Dict[str, List[CalendarBooking]] = {}

    current_date = start_date.date()
    end_date_only = end_date.date()

    while current_date <= end_date_only:
        date_str = current_date.isoformat()
        calendar[date_str] = []
        current_date += timedelta(days=1)

    for booking in bookings:
        booking_start = booking.start_time
        booking_end = booking.end_time

        if target_timezone and target_timezone != settings.DEFAULT_TIMEZONE:
            booking_start = _convert_timezone(
                booking_start, settings.DEFAULT_TIMEZONE, target_timezone
            )
            booking_end = _convert_timezone(
                booking_end, settings.DEFAULT_TIMEZONE, target_timezone
            )

        booking_start_date = booking_start.date()
        booking_end_date = booking_end.date()

        current_booking_date = booking_start_date
        while current_booking_date <= booking_end_date:
            date_str = current_booking_date.isoformat()
            if date_str in calendar:
                calendar[date_str].append(
                    CalendarBooking(
                        id=booking.id,
                        room_id=booking.room_id,
                        title=booking.title,
                        start_time=booking_start,
                        end_time=booking_end,
                        status=booking.status,
                        user_id=booking.user_id,
                    )
                )
            current_booking_date += timedelta(days=1)

    room_responses = [
        RoomListResponse(
            id=room.id,
            name=room.name,
            location=room.location,
            capacity=room.capacity,
            is_active=room.is_active,
            requires_approval=room.requires_approval,
            timezone=room.timezone,
        )
        for room in rooms
    ]

    return CalendarViewResponse(
        start_date=start_date,
        end_date=end_date,
        timezone=target_timezone,
        rooms=room_responses,
        calendar=calendar,
    )


@router.get("/room/{room_id}/daily")
async def get_room_daily_view(
    room_id: int,
    date: Optional[datetime] = None,
    timezone: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    if date is None:
        date = datetime.now()

    target_timezone = timezone or current_user.timezone or settings.DEFAULT_TIMEZONE

    day_start = date.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)

    room = db.query(Room).filter(Room.id == room_id, Room.is_active == True).first()
    if not room:
        raise HTTPException(status_code=404, detail="会议室不存在或未启用")

    bookings = (
        db.query(Booking)
        .filter(
            and_(
                Booking.room_id == room_id,
                Booking.start_time < day_end,
                Booking.end_time > day_start,
                Booking.status != BookingStatus.CANCELLED,
                Booking.status != BookingStatus.SKIPPED,
            )
        )
        .order_by(Booking.start_time)
        .all()
    )

    time_slots = []
    current_slot = day_start
    while current_slot < day_end:
        slot_end = current_slot + timedelta(minutes=30)
        slot_bookings = [
            b
            for b in bookings
            if b.start_time < slot_end and b.end_time > current_slot
        ]

        display_start = current_slot
        display_end = slot_end
        if target_timezone and target_timezone != settings.DEFAULT_TIMEZONE:
            display_start = _convert_timezone(
                display_start, settings.DEFAULT_TIMEZONE, target_timezone
            )
            display_end = _convert_timezone(
                display_end, settings.DEFAULT_TIMEZONE, target_timezone
            )

        time_slots.append(
            {
                "start_time": display_start,
                "end_time": display_end,
                "available": len(slot_bookings) == 0,
                "bookings": [
                    {
                        "id": b.id,
                        "title": b.title,
                        "start_time": b.start_time,
                        "end_time": b.end_time,
                        "user_id": b.user_id,
                    }
                    for b in slot_bookings
                ],
            }
        )
        current_slot = slot_end

    return {
        "date": day_start.date(),
        "room_id": room_id,
        "room_name": room.name,
        "timezone": target_timezone,
        "time_slots": time_slots,
    }


@router.get("/week")
async def get_week_view(
    start_of_week: Optional[datetime] = None,
    room_ids: Optional[List[int]] = Query(None),
    timezone: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    if start_of_week is None:
        today = datetime.now().date()
        start_of_week = datetime.combine(
            today - timedelta(days=today.weekday()), datetime.min.time()
        )
    else:
        start_of_week = start_of_week.replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        start_of_week = start_of_week - timedelta(days=start_of_week.weekday())

    end_of_week = start_of_week + timedelta(days=6, hours=23, minutes=59, seconds=59)

    return await get_calendar_view(
        start_date=start_of_week,
        end_date=end_of_week,
        room_ids=room_ids,
        user_id=None,
        timezone=timezone,
        db=db,
        current_user=current_user,
    )


@router.get("/month")
async def get_month_view(
    year: Optional[int] = None,
    month: Optional[int] = None,
    room_ids: Optional[List[int]] = Query(None),
    timezone: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    if year is None or month is None:
        now = datetime.now()
        year = now.year
        month = now.month

    if month < 1 or month > 12:
        raise HTTPException(status_code=400, detail="月份必须在1-12之间")

    start_of_month = datetime(year, month, 1, 0, 0, 0)

    if month == 12:
        end_of_month = datetime(year + 1, 1, 1, 0, 0, 0)
    else:
        end_of_month = datetime(year, month + 1, 1, 0, 0, 0)

    return await get_calendar_view(
        start_date=start_of_month,
        end_date=end_of_month,
        room_ids=room_ids,
        user_id=None,
        timezone=timezone,
        db=db,
        current_user=current_user,
    )


@router.get("/available-slots", response_model=AvailableSlotsResponse)
async def get_available_slots(
    start_date: datetime,
    end_date: datetime,
    duration_minutes: int = Query(60, ge=15, le=480),
    room_id: Optional[int] = None,
    room_ids: Optional[List[int]] = Query(None),
    device_ids: Optional[List[int]] = Query(None),
    min_capacity: Optional[int] = Query(None, ge=1),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    if end_date <= start_date:
        raise HTTPException(status_code=400, detail="结束日期必须晚于开始日期")

    if (end_date - start_date).days > 30:
        raise HTTPException(status_code=400, detail="查询范围不能超过30天")

    if not room_id and not room_ids:
        raise HTTPException(status_code=400, detail="必须指定 room_id 或 room_ids")

    target_room_ids = room_ids or [room_id] if room_id else []

    if device_ids and not room_id and not room_ids:
        rooms_with_devices = (
            db.query(Room)
            .join(RoomDevice)
            .filter(
                Room.is_active == True,
                RoomDevice.is_permanent == True,
                RoomDevice.device_id.in_(device_ids),
            )
            .all()
        )
        target_room_ids = [r.id for r in rooms_with_devices] if rooms_with_devices else []

    if not target_room_ids:
        return AvailableSlotsResponse(available_slots=[], total_count=0)

    slots_data = get_available_slots_with_devices(
        db,
        target_room_ids,
        start_date,
        end_date,
        duration_minutes,
        device_ids,
        min_capacity,
    )

    available_slots = [
        AvailableSlot(
            room_id=slot["room_id"],
            room_name=slot["room_name"],
            start_time=slot["start_time"],
            end_time=slot["end_time"],
            duration_minutes=slot["duration_minutes"],
            has_all_devices=slot["has_all_devices"],
            available_device_ids=slot["available_device_ids"],
        )
        for slot in slots_data
    ]

    return AvailableSlotsResponse(
        available_slots=available_slots,
        total_count=len(available_slots),
    )
