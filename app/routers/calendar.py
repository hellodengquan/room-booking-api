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
)
from app.schemas.schemas import (
    CalendarViewResponse,
    CalendarBooking,
    RoomListResponse,
)

router = APIRouter(prefix="/calendar", tags=["日历视图"])


@router.get("/view", response_model=CalendarViewResponse)
async def get_calendar_view(
    start_date: datetime,
    end_date: datetime,
    room_ids: Optional[List[int]] = Query(None),
    user_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    if end_date <= start_date:
        raise HTTPException(status_code=400, detail="结束日期必须晚于开始日期")

    if (end_date - start_date).days > 365:
        raise HTTPException(status_code=400, detail="查询范围不能超过365天")

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
        booking_start_date = booking.start_time.date()
        booking_end_date = booking.end_time.date()

        current_booking_date = booking_start_date
        while current_booking_date <= booking_end_date:
            date_str = current_booking_date.isoformat()
            if date_str in calendar:
                calendar[date_str].append(
                    CalendarBooking(
                        id=booking.id,
                        room_id=booking.room_id,
                        title=booking.title,
                        start_time=booking.start_time,
                        end_time=booking.end_time,
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
        )
        for room in rooms
    ]

    return CalendarViewResponse(
        start_date=start_date,
        end_date=end_date,
        rooms=room_responses,
        calendar=calendar,
    )


@router.get("/room/{room_id}/daily")
async def get_room_daily_view(
    room_id: int,
    date: Optional[datetime] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    if date is None:
        date = datetime.now()

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

        time_slots.append(
            {
                "start_time": current_slot,
                "end_time": slot_end,
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
        "time_slots": time_slots,
    }


@router.get("/week")
async def get_week_view(
    start_of_week: Optional[datetime] = None,
    room_ids: Optional[List[int]] = Query(None),
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
        db=db,
        current_user=current_user,
    )


@router.get("/month")
async def get_month_view(
    year: Optional[int] = None,
    month: Optional[int] = None,
    room_ids: Optional[List[int]] = Query(None),
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
        db=db,
        current_user=current_user,
    )


@router.get("/available-slots")
async def get_available_slots(
    room_id: int,
    start_date: datetime,
    end_date: datetime,
    duration_minutes: int = Query(60, ge=15, le=480),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    if end_date <= start_date:
        raise HTTPException(status_code=400, detail="结束日期必须晚于开始日期")

    if (end_date - start_date).days > 30:
        raise HTTPException(status_code=400, detail="查询范围不能超过30天")

    room = db.query(Room).filter(Room.id == room_id, Room.is_active == True).first()
    if not room:
        raise HTTPException(status_code=404, detail="会议室不存在或未启用")

    bookings = (
        db.query(Booking)
        .filter(
            and_(
                Booking.room_id == room_id,
                Booking.start_time <= end_date,
                Booking.end_time >= start_date,
                Booking.status != BookingStatus.CANCELLED,
            )
        )
        .order_by(Booking.start_time)
        .all()
    )

    available_slots = []
    current_time = start_date
    duration = timedelta(minutes=duration_minutes)

    while current_time + duration <= end_date:
        slot_end = current_time + duration
        is_available = True

        for booking in bookings:
            if not (booking.end_time <= current_time or booking.start_time >= slot_end):
                is_available = False
                break

        if is_available:
            available_slots.append(
                {
                    "start_time": current_time,
                    "end_time": slot_end,
                    "duration_minutes": duration_minutes,
                }
            )
            current_time = slot_end
        else:
            current_time += timedelta(minutes=15)

    return {
        "room_id": room_id,
        "room_name": room.name,
        "search_start": start_date,
        "search_end": end_date,
        "duration_minutes": duration_minutes,
        "available_slots": available_slots,
        "total_available": len(available_slots),
    }
