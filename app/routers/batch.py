from datetime import datetime
from typing import List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from sqlalchemy import and_

from app.database import get_db
from app.dependencies import get_current_active_user
from app.models.models import (
    Booking,
    BookingStatus,
    User,
    PermissionLevel,
)
from app.schemas.schemas import (
    BatchCancelRequest,
    BatchCancelResponse,
)

router = APIRouter(prefix="/batch", tags=["批量操作"])


@router.post("/cancel", response_model=BatchCancelResponse)
async def batch_cancel_bookings(
    cancel_request: BatchCancelRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    if (
        not cancel_request.booking_ids
        and not cancel_request.series_id
        and not cancel_request.start_date
        and not cancel_request.end_date
        and not cancel_request.user_id
        and not cancel_request.room_id
        and not cancel_request.cancel_all
    ):
        raise HTTPException(
            status_code=400,
            detail="请提供至少一个筛选条件或设置 cancel_all=True",
        )

    query = db.query(Booking).filter(
        Booking.status != BookingStatus.CANCELLED,
        Booking.start_time >= datetime.now(),
    )

    if cancel_request.booking_ids:
        query = query.filter(Booking.id.in_(cancel_request.booking_ids))

    if cancel_request.series_id:
        query = query.filter(Booking.series_id == cancel_request.series_id)

    if cancel_request.start_date:
        query = query.filter(Booking.start_time >= cancel_request.start_date)

    if cancel_request.end_date:
        query = query.filter(Booking.end_time <= cancel_request.end_date)

    if cancel_request.user_id:
        query = query.filter(Booking.user_id == cancel_request.user_id)

    if cancel_request.room_id:
        query = query.filter(Booking.room_id == cancel_request.room_id)

    if (
        current_user.permission_level != PermissionLevel.ADMIN
        and not cancel_request.cancel_all
    ):
        query = query.filter(Booking.user_id == current_user.id)

    if cancel_request.cancel_all and current_user.permission_level != PermissionLevel.ADMIN:
        query = query.filter(Booking.user_id == current_user.id)

    bookings_to_cancel = query.all()

    cancelled_ids: List[int] = []
    errors: List[Dict[str, Any]] = []

    for booking in bookings_to_cancel:
        try:
            if (
                current_user.permission_level != PermissionLevel.ADMIN
                and booking.user_id != current_user.id
            ):
                errors.append(
                    {
                        "booking_id": booking.id,
                        "error": "没有权限取消此预订",
                    }
                )
                continue

            booking.status = BookingStatus.CANCELLED
            cancelled_ids.append(booking.id)
        except Exception as e:
            errors.append(
                {
                    "booking_id": booking.id,
                    "error": str(e),
                }
            )

    db.commit()

    return BatchCancelResponse(
        cancelled_count=len(cancelled_ids),
        cancelled_ids=cancelled_ids,
        failed_count=len(errors),
        errors=errors,
    )


@router.delete("/cancel/user/{user_id}", response_model=BatchCancelResponse)
async def cancel_user_bookings(
    user_id: int,
    start_date: datetime = None,
    end_date: datetime = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    if (
        current_user.permission_level != PermissionLevel.ADMIN
        and current_user.id != user_id
    ):
        raise HTTPException(
            status_code=403,
            detail="您没有权限取消其他用户的预订",
        )

    query = db.query(Booking).filter(
        Booking.user_id == user_id,
        Booking.status != BookingStatus.CANCELLED,
        Booking.start_time >= datetime.now(),
    )

    if start_date:
        query = query.filter(Booking.start_time >= start_date)
    if end_date:
        query = query.filter(Booking.end_time <= end_date)

    bookings_to_cancel = query.all()

    cancelled_ids: List[int] = []
    errors: List[Dict[str, Any]] = []

    for booking in bookings_to_cancel:
        try:
            booking.status = BookingStatus.CANCELLED
            cancelled_ids.append(booking.id)
        except Exception as e:
            errors.append(
                {
                    "booking_id": booking.id,
                    "error": str(e),
                }
            )

    db.commit()

    return BatchCancelResponse(
        cancelled_count=len(cancelled_ids),
        cancelled_ids=cancelled_ids,
        failed_count=len(errors),
        errors=errors,
    )


@router.delete("/cancel/room/{room_id}", response_model=BatchCancelResponse)
async def cancel_room_bookings(
    room_id: int,
    start_date: datetime = None,
    end_date: datetime = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    if current_user.permission_level != PermissionLevel.ADMIN:
        raise HTTPException(
            status_code=403,
            detail="只有管理员可以取消会议室的所有预订",
        )

    query = db.query(Booking).filter(
        Booking.room_id == room_id,
        Booking.status != BookingStatus.CANCELLED,
        Booking.start_time >= datetime.now(),
    )

    if start_date:
        query = query.filter(Booking.start_time >= start_date)
    if end_date:
        query = query.filter(Booking.end_time <= end_date)

    bookings_to_cancel = query.all()

    cancelled_ids: List[int] = []
    errors: List[Dict[str, Any]] = []

    for booking in bookings_to_cancel:
        try:
            booking.status = BookingStatus.CANCELLED
            cancelled_ids.append(booking.id)
        except Exception as e:
            errors.append(
                {
                    "booking_id": booking.id,
                    "error": str(e),
                }
            )

    db.commit()

    return BatchCancelResponse(
        cancelled_count=len(cancelled_ids),
        cancelled_ids=cancelled_ids,
        failed_count=len(errors),
        errors=errors,
    )


@router.post("/cancel/old", response_model=BatchCancelResponse)
async def cancel_old_bookings(
    days_old: int = 30,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    if current_user.permission_level != PermissionLevel.ADMIN:
        raise HTTPException(
            status_code=403,
            detail="只有管理员可以批量取消历史预订",
        )

    cutoff_date = datetime.now() - timedelta(days=days_old)

    bookings_to_cancel = (
        db.query(Booking)
        .filter(
            Booking.end_time < cutoff_date,
            Booking.status != BookingStatus.CANCELLED,
        )
        .all()
    )

    cancelled_ids: List[int] = []
    errors: List[Dict[str, Any]] = []

    for booking in bookings_to_cancel:
        try:
            booking.status = BookingStatus.CANCELLED
            cancelled_ids.append(booking.id)
        except Exception as e:
            errors.append(
                {
                    "booking_id": booking.id,
                    "error": str(e),
                }
            )

    db.commit()

    return BatchCancelResponse(
        cancelled_count=len(cancelled_ids),
        cancelled_ids=cancelled_ids,
        failed_count=len(errors),
        errors=errors,
    )
