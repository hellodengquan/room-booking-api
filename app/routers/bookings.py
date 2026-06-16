from datetime import datetime
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query, Body
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_active_user, require_booking
from app.models.models import (
    Booking,
    Room,
    User,
    BookingStatus,
    BookingDevice,
    Device,
    RecurrenceType,
    PermissionLevel,
    BookingSkip,
)
from app.schemas.schemas import (
    BookingCreate,
    BookingUpdate,
    BookingResponse,
    BookingListResponse,
    ConflictInfo,
    AlternativeSuggestion,
    BookingSkipCreate,
    BookingSkipResponse,
)
from app.services.booking_service import (
    check_time_conflict,
    check_device_conflict,
    find_alternative_slots,
    create_recurring_bookings,
    skip_booking,
    check_delegation_permission,
)

router = APIRouter(prefix="/bookings", tags=["预订管理"])


@router.get("", response_model=List[BookingListResponse])
async def list_bookings(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    room_id: Optional[int] = None,
    user_id: Optional[int] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    status: Optional[BookingStatus] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    query = db.query(
        Booking,
        Room.name.label("room_name"),
        User.username.label("user_name"),
    ).join(Room, Booking.room_id == Room.id).join(User, Booking.user_id == User.id)

    if room_id:
        query = query.filter(Booking.room_id == room_id)
    if user_id:
        query = query.filter(Booking.user_id == user_id)
    if start_date:
        query = query.filter(Booking.start_time >= start_date)
    if end_date:
        query = query.filter(Booking.end_time <= end_date)
    if status:
        query = query.filter(Booking.status == status)

    results = query.order_by(Booking.start_time).offset(skip).limit(limit).all()

    response = []
    for booking, room_name, user_name in results:
        response.append(
            BookingListResponse(
                id=booking.id,
                room_id=booking.room_id,
                room_name=room_name,
                user_id=booking.user_id,
                user_name=user_name,
                title=booking.title,
                start_time=booking.start_time,
                end_time=booking.end_time,
                status=booking.status,
                attendee_count=booking.attendee_count,
            )
        )
    return response


@router.get("/check-conflict")
async def check_conflict(
    room_id: int,
    start_time: datetime,
    end_time: datetime,
    device_ids: Optional[List[int]] = Query(None),
    exclude_booking_id: Optional[int] = None,
    attendee_count: Optional[int] = Query(1, ge=1),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    if end_time <= start_time:
        raise HTTPException(status_code=400, detail="结束时间必须晚于开始时间")

    time_conflicts = check_time_conflict(
        db, room_id, start_time, end_time, exclude_booking_id
    )
    device_conflicts = check_device_conflict(
        db, device_ids or [], start_time, end_time, exclude_booking_id
    )

    alternatives = []
    if time_conflicts or device_conflicts:
        alternatives = find_alternative_slots(
            db, room_id, start_time, end_time, exclude_booking_id,
            required_device_ids=device_ids,
            required_capacity=attendee_count,
        )

    return {
        "has_conflict": len(time_conflicts) + len(device_conflicts) > 0,
        "time_conflicts": time_conflicts,
        "device_conflicts": device_conflicts,
        "alternatives": alternatives,
    }


@router.get("/{booking_id}", response_model=BookingResponse)
async def get_booking(
    booking_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="预订不存在")

    return booking


@router.post("", response_model=Dict[str, Any], status_code=201)
async def create_booking(
    booking_in: BookingCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    from app.services.booking_service import check_user_permission

    booking_user_id = current_user.id
    delegation_id = None

    if booking_in.delegate_user_id and booking_in.delegate_user_id != current_user.id:
        delegation = check_delegation_permission(
            db, booking_in.delegate_user_id, current_user.id, booking_in.room_id
        )
        if not delegation:
            raise HTTPException(
                status_code=403,
                detail="您没有权限代此用户预订",
            )
        booking_user_id = booking_in.delegate_user_id
        delegation_id = delegation.id

    if not check_user_permission(
        db, booking_user_id, booking_in.room_id, PermissionLevel.BOOK
    ):
        raise HTTPException(
            status_code=403,
            detail="您没有预订此会议室的权限",
        )

    room = db.query(Room).filter(Room.id == booking_in.room_id).first()
    if not room or not room.is_active:
        raise HTTPException(status_code=404, detail="会议室不存在或未启用")

    duration_minutes = (booking_in.end_time - booking_in.start_time).total_seconds() / 60
    if duration_minutes < room.min_booking_duration:
        raise HTTPException(
            status_code=400,
            detail=f"预订时长不能少于 {room.min_booking_duration} 分钟",
        )
    if duration_minutes > room.max_booking_duration:
        raise HTTPException(
            status_code=400,
            detail=f"预订时长不能超过 {room.max_booking_duration} 分钟",
        )

    if booking_in.attendee_count > room.capacity:
        raise HTTPException(
            status_code=400,
            detail=f"参会人数不能超过会议室容量 {room.capacity} 人",
        )

    if booking_in.start_time < datetime.now():
        raise HTTPException(status_code=400, detail="不能预订过去的时间")

    time_conflicts = check_time_conflict(
        db, booking_in.room_id, booking_in.start_time, booking_in.end_time
    )
    device_conflicts = check_device_conflict(
        db, booking_in.device_ids or [], booking_in.start_time, booking_in.end_time
    )

    all_conflicts = time_conflicts + device_conflicts

    if all_conflicts:
        alternatives = find_alternative_slots(
            db,
            booking_in.room_id,
            booking_in.start_time,
            booking_in.end_time,
            required_device_ids=booking_in.device_ids,
            required_capacity=booking_in.attendee_count,
        )
        return {
            "success": False,
            "message": "存在预订冲突",
            "conflicts": all_conflicts,
            "alternatives": alternatives,
        }

    created_bookings, errors = create_recurring_bookings(
        db, booking_in, booking_user_id, delegation_id
    )

    if not created_bookings and errors:
        alternatives = find_alternative_slots(
            db,
            booking_in.room_id,
            booking_in.start_time,
            booking_in.end_time,
            required_device_ids=booking_in.device_ids,
            required_capacity=booking_in.attendee_count,
        )
        return {
            "success": False,
            "message": "所有时段均存在冲突",
            "errors": errors,
            "alternatives": alternatives,
        }

    response_bookings = []
    for booking in created_bookings:
        response_bookings.append(
            BookingResponse(
                id=booking.id,
                room_id=booking.room_id,
                user_id=booking.user_id,
                title=booking.title,
                description=booking.description,
                start_time=booking.start_time,
                end_time=booking.end_time,
                status=booking.status,
                recurrence_type=booking.recurrence_type,
                recurrence_end_date=booking.recurrence_end_date,
                recurrence_weekdays=booking.recurrence_weekdays,
                recurrence_interval=booking.recurrence_interval,
                series_id=booking.series_id,
                attendee_count=booking.attendee_count,
                delegation_id=booking.delegation_id,
                created_at=booking.created_at,
                updated_at=booking.updated_at,
            )
        )

    return {
        "success": True,
        "message": f"成功创建 {len(created_bookings)} 个预订",
        "bookings": response_bookings,
        "errors": errors if errors else None,
        "delegation_id": delegation_id,
    }


@router.put("/{booking_id}", response_model=BookingResponse)
async def update_booking(
    booking_id: int,
    booking_in: BookingUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    db_booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not db_booking:
        raise HTTPException(status_code=404, detail="预订不存在")

    if (
        current_user.id != db_booking.user_id
        and current_user.permission_level != PermissionLevel.ADMIN
    ):
        raise HTTPException(
            status_code=403,
            detail="您没有权限修改此预订",
        )

    if db_booking.status == BookingStatus.CANCELLED:
        raise HTTPException(status_code=400, detail="已取消的预订无法修改")

    update_data = booking_in.model_dump(exclude_unset=True)

    room_id = update_data.get("room_id", db_booking.room_id)
    start_time = update_data.get("start_time", db_booking.start_time)
    end_time = update_data.get("end_time", db_booking.end_time)
    device_ids = update_data.get("device_ids")

    if end_time <= start_time:
        raise HTTPException(status_code=400, detail="结束时间必须晚于开始时间")

    if start_time < datetime.now():
        raise HTTPException(status_code=400, detail="不能预订过去的时间")

    time_conflicts = check_time_conflict(
        db, room_id, start_time, end_time, exclude_booking_id=booking_id
    )

    if time_conflicts:
        alternatives = find_alternative_slots(
            db, room_id, start_time, end_time, exclude_booking_id=booking_id
        )
        raise HTTPException(
            status_code=409,
            detail={
                "message": "存在时间冲突",
                "conflicts": time_conflicts,
                "alternatives": alternatives,
            },
        )

    if device_ids is not None:
        device_conflicts = check_device_conflict(
            db, device_ids, start_time, end_time, exclude_booking_id=booking_id
        )
        if device_conflicts:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "存在设备冲突",
                    "conflicts": device_conflicts,
                },
            )

        db.query(BookingDevice).filter(BookingDevice.booking_id == booking_id).delete()
        for device_id in device_ids:
            device = db.query(Device).filter(Device.id == device_id).first()
            if device and device.is_available:
                booking_device = BookingDevice(
                    booking_id=booking_id,
                    device_id=device_id,
                )
                db.add(booking_device)

    for field, value in update_data.items():
        if field != "device_ids":
            setattr(db_booking, field, value)

    db.commit()
    db.refresh(db_booking)
    return db_booking


@router.delete("/{booking_id}", status_code=204)
async def cancel_booking(
    booking_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    db_booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not db_booking:
        raise HTTPException(status_code=404, detail="预订不存在")

    if (
        current_user.id != db_booking.user_id
        and current_user.permission_level != PermissionLevel.ADMIN
    ):
        raise HTTPException(
            status_code=403,
            detail="您没有权限取消此预订",
        )

    if db_booking.status == BookingStatus.CANCELLED:
        raise HTTPException(status_code=400, detail="预订已取消")

    db_booking.status = BookingStatus.CANCELLED
    db.commit()
    return None


@router.get("/series/{series_id}", response_model=List[BookingResponse])
async def get_booking_series(
    series_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    bookings = (
        db.query(Booking)
        .filter(Booking.series_id == series_id)
        .order_by(Booking.start_time)
        .all()
    )
    if not bookings:
        raise HTTPException(status_code=404, detail="预订系列不存在")
    return bookings


@router.delete("/series/{series_id}", status_code=200)
async def cancel_booking_series(
    series_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    bookings = (
        db.query(Booking)
        .filter(
            Booking.series_id == series_id,
            Booking.status != BookingStatus.CANCELLED,
        )
        .all()
    )

    if not bookings:
        raise HTTPException(status_code=404, detail="预订系列不存在")

    if current_user.permission_level != PermissionLevel.ADMIN:
        for booking in bookings:
            if booking.user_id != current_user.id:
                raise HTTPException(
                    status_code=403,
                    detail="您没有权限取消此系列中的所有预订",
                )

    cancelled_count = 0
    for booking in bookings:
        if booking.start_time >= datetime.now():
            booking.status = BookingStatus.CANCELLED
            cancelled_count += 1

    db.commit()

    return {
        "message": f"已取消 {cancelled_count} 个预订",
        "cancelled_count": cancelled_count,
        "total_count": len(bookings),
    }


@router.post("/skip", response_model=Dict[str, Any])
async def skip_booking_route(
    skip_in: BookingSkipCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    if skip_in.booking_id:
        booking = db.query(Booking).filter(Booking.id == skip_in.booking_id).first()
        if not booking:
            raise HTTPException(status_code=404, detail="预订不存在")
        if (
            booking.user_id != current_user.id
            and current_user.permission_level != PermissionLevel.ADMIN
        ):
            raise HTTPException(
                status_code=403,
                detail="您没有权限跳过此预订",
            )
    elif skip_in.series_id:
        bookings = (
            db.query(Booking)
            .filter(Booking.series_id == skip_in.series_id)
            .first()
        )
        if not bookings:
            raise HTTPException(status_code=404, detail="预订系列不存在")
        if (
            bookings.user_id != current_user.id
            and current_user.permission_level != PermissionLevel.ADMIN
        ):
            raise HTTPException(
                status_code=403,
                detail="您没有权限跳过此系列中的预订",
            )

    success, message = skip_booking(db, skip_in, current_user.id)
    if not success:
        raise HTTPException(status_code=400, detail=message)

    return {"success": True, "message": message}


@router.get("/skips/series/{series_id}", response_model=List[BookingSkipResponse])
async def get_series_skips(
    series_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    skips = (
        db.query(BookingSkip)
        .filter(BookingSkip.series_id == series_id)
        .order_by(BookingSkip.skip_date.desc())
        .all()
    )

    if skips:
        sample_booking = (
            db.query(Booking).filter(Booking.series_id == series_id).first()
        )
        if sample_booking and sample_booking.user_id != current_user.id:
            if current_user.permission_level != PermissionLevel.ADMIN:
                raise HTTPException(
                    status_code=403,
                    detail="您没有权限查看此系列的跳过记录",
                )

    return skips
