import uuid
import math
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
    BookingSkip,
    BookingDelegation,
    CancellationRequest,
    CancellationRequestStatus,
    CancellationAuditLog,
    SuggestionScoreLevel,
)
from app.schemas.schemas import (
    BookingCreate,
    ConflictInfo,
    AlternativeSuggestion,
    RecurrenceConfig,
    BookingSkipCreate,
    BookingDelegationCreate,
    BatchCancelRequest,
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


def _calculate_suggestion_score(
    room: Room,
    desired_start: datetime,
    actual_start: datetime,
    desired_end: datetime,
    actual_end: datetime,
    original_room_id: int,
    required_device_ids: Optional[List[int]] = None,
    required_capacity: int = 1,
    db: Session = None,
) -> Tuple[float, List[str], bool, bool]:
    score = 0.0
    reasons = []

    time_diff_minutes = abs((actual_start - desired_start).total_seconds()) / 60
    if time_diff_minutes == 0:
        time_score = 1.0
        reasons.append("时间完全匹配")
    elif time_diff_minutes <= 30:
        time_score = 0.9 - (time_diff_minutes / 300)
        reasons.append(f"时间偏差 {int(time_diff_minutes)} 分钟")
    elif time_diff_minutes <= 120:
        time_score = 0.7 - (time_diff_minutes / 400)
        reasons.append(f"时间偏差 {int(time_diff_minutes)} 分钟")
    else:
        time_score = max(0.1, 0.4 - (time_diff_minutes / 1440))
        reasons.append(f"时间偏差较大 ({int(time_diff_minutes)} 分钟)")

    if room.id == original_room_id:
        room_score = 1.0
        reasons.append("原会议室")
    else:
        capacity_diff = abs(room.capacity - required_capacity)
        if room.capacity >= required_capacity:
            if room.capacity <= required_capacity + 5:
                room_score = 0.8
                reasons.append("相似容量会议室")
            else:
                room_score = 0.6
                reasons.append("更大容量会议室")
        else:
            room_score = 0.3
            reasons.append("容量较小会议室")

    has_devices = True
    if required_device_ids and db:
        room_device_ids = [
            rd.device_id
            for rd in room.room_devices
            if rd.is_permanent
        ]
        available_count = sum(1 for d in required_device_ids if d in room_device_ids)
        if available_count == len(required_device_ids):
            device_score = 1.0
            reasons.append("所有设备可用")
        elif available_count > 0:
            device_score = 0.5 * (available_count / len(required_device_ids))
            reasons.append(f"部分设备可用 ({available_count}/{len(required_device_ids)})")
            has_devices = False
        else:
            device_score = 0.1
            reasons.append("缺少所需设备")
            has_devices = False
    else:
        device_score = 0.5

    capacity_match = room.capacity >= required_capacity

    final_score = (
        time_score * settings.SUGGESTION_SCORE_WEIGHT_TIME
        + room_score * settings.SUGGESTION_SCORE_WEIGHT_ROOM
        + device_score * settings.SUGGESTION_SCORE_WEIGHT_DEVICE
    )

    return final_score, reasons, has_devices, capacity_match


def _determine_score_level(score: float) -> SuggestionScoreLevel:
    if score >= 0.85:
        return SuggestionScoreLevel.EXCELLENT
    elif score >= 0.7:
        return SuggestionScoreLevel.GOOD
    elif score >= 0.5:
        return SuggestionScoreLevel.FAIR
    else:
        return SuggestionScoreLevel.POOR


def find_alternative_slots(
    db: Session,
    room_id: int,
    desired_start: datetime,
    desired_end: datetime,
    exclude_booking_id: Optional[int] = None,
    max_suggestions: int = settings.MAX_ALTERNATIVE_SUGGESTIONS,
    required_device_ids: Optional[List[int]] = None,
    required_capacity: int = 1,
) -> List[AlternativeSuggestion]:
    suggestions = []
    duration = desired_end - desired_start
    duration_minutes = int(duration.total_seconds() / 60)

    original_room = db.query(Room).filter(Room.id == room_id).first()
    if not original_room:
        return suggestions

    all_rooms = db.query(Room).filter(Room.is_active == True).all()

    time_offsets = [
        timedelta(0),
        timedelta(minutes=30),
        timedelta(minutes=-30),
        timedelta(hours=1),
        timedelta(hours=-1),
        timedelta(hours=2),
        timedelta(hours=-2),
        timedelta(days=1),
        timedelta(days=-1),
        timedelta(days=2),
        timedelta(days=-2),
    ]

    candidate_slots = []
    for room in all_rooms:
        for offset in time_offsets:
            start = desired_start + offset
            end = desired_end + offset
            if start < datetime.now():
                continue
            candidate_slots.append((room, start, end))

    scored_slots = []
    for room, start, end in candidate_slots:
        conflicts = check_time_conflict(
            db, room.id, start, end,
            exclude_booking_id if room.id == room_id else None
        )
        if conflicts:
            continue

        score, reasons, has_devices, capacity_match = _calculate_suggestion_score(
            room,
            desired_start,
            start,
            desired_end,
            end,
            room_id,
            required_device_ids,
            required_capacity,
            db,
        )

        available_device_ids = []
        if required_device_ids:
            room_device_ids = [
                rd.device_id for rd in room.room_devices if rd.is_permanent
            ]
            available_device_ids = [d for d in required_device_ids if d in room_device_ids]

        scored_slots.append(
            {
                "room": room,
                "start": start,
                "end": end,
                "score": score,
                "reasons": reasons,
                "has_devices": has_devices,
                "capacity_match": capacity_match,
                "available_device_ids": available_device_ids,
            }
        )

    scored_slots.sort(key=lambda x: x["score"], reverse=True)

    for slot in scored_slots[:max_suggestions]:
        suggestions.append(
            AlternativeSuggestion(
                room_id=slot["room"].id,
                room_name=slot["room"].name,
                start_time=slot["start"],
                end_time=slot["end"],
                duration_minutes=duration_minutes,
                score=round(slot["score"], 3),
                score_level=_determine_score_level(slot["score"]),
                score_reasons=slot["reasons"],
                has_required_devices=slot["has_devices"],
                capacity_match=slot["capacity_match"],
            )
        )

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


def check_delegation_permission(
    db: Session, delegator_id: int, delegate_id: int, room_id: Optional[int] = None
) -> Optional[BookingDelegation]:
    now = datetime.now()
    query = db.query(BookingDelegation).filter(
        BookingDelegation.delegator_id == delegator_id,
        BookingDelegation.delegate_id == delegate_id,
        BookingDelegation.is_active == True,
    )

    if room_id:
        query = query.filter(
            or_(
                BookingDelegation.room_id == room_id,
                BookingDelegation.room_id.is_(None),
            )
        )

    delegations = query.all()

    for delegation in delegations:
        if delegation.start_date and delegation.start_date > now:
            continue
        if delegation.end_date and delegation.end_date < now:
            continue
        return delegation

    return None


def create_booking_with_devices(
    db: Session,
    booking_data: BookingCreate,
    user_id: int,
    start_time: datetime,
    end_time: datetime,
    series_id: Optional[str] = None,
    delegation_id: Optional[int] = None,
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
        delegation_id=delegation_id,
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
    delegation_id: Optional[int] = None,
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
                db, booking_data, user_id, start, end, series_id, delegation_id
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


def skip_booking(
    db: Session,
    skip_data: BookingSkipCreate,
    skipped_by: int,
) -> Tuple[bool, str]:
    if skip_data.booking_id:
        booking = db.query(Booking).filter(Booking.id == skip_data.booking_id).first()
        if not booking:
            return False, "预订不存在"
        if booking.status != BookingStatus.CONFIRMED:
            return False, "只有已确认的预订才能跳过"
        if booking.start_time < datetime.now():
            return False, "不能跳过过去的预订"

        booking.status = BookingStatus.SKIPPED
        db_skip = BookingSkip(
            booking_id=booking.id,
            series_id=booking.series_id,
            skip_date=skip_data.skip_date,
            reason=skip_data.reason,
            skipped_by=skipped_by,
        )
        db.add(db_skip)
        db.commit()
        return True, "成功跳过预订"

    elif skip_data.series_id:
        bookings = (
            db.query(Booking)
            .filter(
                Booking.series_id == skip_data.series_id,
                Booking.status == BookingStatus.CONFIRMED,
                Booking.start_time >= datetime.now(),
            )
            .all()
        )

        target_date = skip_data.skip_date.date()
        skipped_count = 0

        for booking in bookings:
            if booking.start_time.date() == target_date:
                booking.status = BookingStatus.SKIPPED
                db_skip = BookingSkip(
                    booking_id=booking.id,
                    series_id=skip_data.series_id,
                    skip_date=skip_data.skip_date,
                    reason=skip_data.reason,
                    skipped_by=skipped_by,
                )
                db.add(db_skip)
                skipped_count += 1

        db.commit()
        if skipped_count > 0:
            return True, f"成功跳过 {skipped_count} 个预订"
        else:
            return False, "未找到可跳过的预订"

    return False, "必须指定 booking_id 或 series_id"


def create_delegation(
    db: Session,
    delegator_id: int,
    delegation_data: BookingDelegationCreate,
) -> BookingDelegation:
    from datetime import timedelta as td

    start_date = delegation_data.start_date or datetime.now()
    end_date = delegation_data.end_date or datetime.now() + td(
        days=settings.DELEGATION_DEFAULT_DURATION_DAYS
    )

    delegation = BookingDelegation(
        delegator_id=delegator_id,
        delegate_id=delegation_data.delegate_id,
        room_id=delegation_data.room_id,
        is_active=True,
        start_date=start_date,
        end_date=end_date,
        reason=delegation_data.reason,
    )
    db.add(delegation)
    db.commit()
    db.refresh(delegation)
    return delegation


def get_user_delegations(
    db: Session,
    user_id: int,
    as_delegator: bool = True,
) -> List[BookingDelegation]:
    if as_delegator:
        return (
            db.query(BookingDelegation)
            .filter(BookingDelegation.delegator_id == user_id)
            .order_by(BookingDelegation.created_at.desc())
            .all()
        )
    else:
        return (
            db.query(BookingDelegation)
            .filter(BookingDelegation.delegate_id == user_id)
            .order_by(BookingDelegation.created_at.desc())
            .all()
        )


def create_cancellation_request(
    db: Session,
    requester_id: int,
    booking_ids: List[int],
    reason: Optional[str] = None,
    cancellation_type: str = "ids",
    params: Optional[Dict[str, Any]] = None,
) -> CancellationRequest:
    request = CancellationRequest(
        requester_id=requester_id,
        status=CancellationRequestStatus.PENDING,
        reason=reason,
        booking_ids=booking_ids,
        cancellation_type=cancellation_type,
        params=params,
    )
    db.add(request)
    db.commit()
    db.refresh(request)
    return request


def approve_cancellation(
    db: Session,
    request_id: int,
    approver_id: int,
    approve: bool = True,
    approval_reason: Optional[str] = None,
) -> Tuple[bool, str, List[int]]:
    request = (
        db.query(CancellationRequest)
        .filter(CancellationRequest.id == request_id)
        .first()
    )
    if not request:
        return False, "取消申请不存在", []

    if request.status != CancellationRequestStatus.PENDING:
        return False, "该申请已处理", []

    cancelled_ids = []

    if approve:
        for booking_id in request.booking_ids:
            booking = db.query(Booking).filter(Booking.id == booking_id).first()
            if booking and booking.status == BookingStatus.CONFIRMED:
                audit_log = CancellationAuditLog(
                    request_id=request.id,
                    booking_id=booking.id,
                    original_status=booking.status,
                    new_status=BookingStatus.CANCELLED,
                    action_type="cancellation",
                    action_by=approver_id,
                )
                db.add(audit_log)

                booking.status = BookingStatus.CANCELLED
                cancelled_ids.append(booking_id)

        request.status = CancellationRequestStatus.APPROVED
        request.approver_id = approver_id
        request.approval_reason = approval_reason
        request.approved_at = datetime.now()
    else:
        request.status = CancellationRequestStatus.REJECTED
        request.approver_id = approver_id
        request.approval_reason = approval_reason

    db.commit()

    if approve:
        return True, f"已批准取消 {len(cancelled_ids)} 个预订", cancelled_ids
    else:
        return True, "已拒绝取消申请", []


def rollback_cancellation(
    db: Session,
    request_id: int,
    roller_back_id: int,
    reason: Optional[str] = None,
) -> Tuple[bool, str, List[int]]:
    request = (
        db.query(CancellationRequest)
        .filter(CancellationRequest.id == request_id)
        .first()
    )
    if not request:
        return False, "取消申请不存在", []

    if request.status != CancellationRequestStatus.APPROVED:
        return False, "只有已批准的取消才能回滚", []

    audit_logs = (
        db.query(CancellationAuditLog)
        .filter(
            CancellationAuditLog.request_id == request_id,
            CancellationAuditLog.action_type == "cancellation",
        )
        .all()
    )

    restored_ids = []
    for audit_log in audit_logs:
        booking = (
            db.query(Booking).filter(Booking.id == audit_log.booking_id).first()
        )
        if booking and booking.status == BookingStatus.CANCELLED:
            rollback_log = CancellationAuditLog(
                request_id=request.id,
                booking_id=booking.id,
                original_status=booking.status,
                new_status=audit_log.original_status,
                action_type="rollback",
                action_by=roller_back_id,
            )
            db.add(rollback_log)

            booking.status = audit_log.original_status
            restored_ids.append(booking.id)

    request.status = CancellationRequestStatus.ROLLBACK
    request.rolled_back_at = datetime.now()

    db.commit()

    return True, f"已回滚 {len(restored_ids)} 个预订", restored_ids


def batch_cancel_with_audit(
    db: Session,
    cancel_request: BatchCancelRequest,
    user_id: int,
    is_admin: bool = False,
) -> Tuple[List[int], List[Dict[str, Any]], Optional[CancellationRequest]]:
    cancelled_ids = []
    errors = []
    cancellation_request = None

    query = db.query(Booking).filter(Booking.status == BookingStatus.CONFIRMED)

    if not is_admin:
        query = query.filter(Booking.user_id == user_id)

    if cancel_request.booking_ids:
        query = query.filter(Booking.id.in_(cancel_request.booking_ids))
    if cancel_request.series_id:
        query = query.filter(Booking.series_id == cancel_request.series_id)
    if cancel_request.start_date:
        query = query.filter(Booking.start_time >= cancel_request.start_date)
    if cancel_request.end_date:
        query = query.filter(Booking.end_time <= cancel_request.end_date)
    if cancel_request.user_id and is_admin:
        query = query.filter(Booking.user_id == cancel_request.user_id)
    if cancel_request.room_id:
        query = query.filter(Booking.room_id == cancel_request.room_id)

    bookings = query.all()

    if cancel_request.require_approval:
        booking_ids = [b.id for b in bookings]
        cancellation_request = create_cancellation_request(
            db,
            user_id,
            booking_ids,
            cancel_request.reason,
            "batch",
            cancel_request.model_dump() if hasattr(cancel_request, 'model_dump') else None,
        )
        return [], [{"message": "已提交取消审批申请"}], cancellation_request

    for booking in bookings:
        try:
            booking.status = BookingStatus.CANCELLED
            cancelled_ids.append(booking.id)
        except Exception as e:
            errors.append({"booking_id": booking.id, "error": str(e)})

    db.commit()
    return cancelled_ids, errors, None


def get_available_slots_with_devices(
    db: Session,
    room_ids: List[int],
    start_date: datetime,
    end_date: datetime,
    duration_minutes: int,
    device_ids: Optional[List[int]] = None,
    min_capacity: Optional[int] = None,
) -> List[Dict[str, Any]]:
    slots = []
    duration = timedelta(minutes=duration_minutes)

    rooms = db.query(Room).filter(
        Room.id.in_(room_ids),
        Room.is_active == True,
    )

    if min_capacity:
        rooms = rooms.filter(Room.capacity >= min_capacity)

    rooms = rooms.all()

    for room in rooms:
        room_device_ids = [
            rd.device_id for rd in room.room_devices if rd.is_permanent
        ]

        if device_ids:
            has_all_devices = all(d in room_device_ids for d in device_ids)
            available_devices = [d for d in device_ids if d in room_device_ids]
        else:
            has_all_devices = True
            available_devices = room_device_ids

        if device_ids and not has_all_devices:
            continue

        bookings = (
            db.query(Booking)
            .filter(
                Booking.room_id == room.id,
                Booking.status == BookingStatus.CONFIRMED,
                Booking.start_time >= start_date,
                Booking.end_time <= end_date,
            )
            .order_by(Booking.start_time)
            .all()
        )

        current_time = start_date
        for booking in bookings:
            if current_time + duration <= booking.start_time:
                slots.append(
                    {
                        "room_id": room.id,
                        "room_name": room.name,
                        "start_time": current_time,
                        "end_time": current_time + duration,
                        "duration_minutes": duration_minutes,
                        "has_all_devices": has_all_devices,
                        "available_device_ids": available_devices,
                    }
                )
            current_time = max(current_time, booking.end_time)

        if current_time + duration <= end_date:
            slots.append(
                {
                    "room_id": room.id,
                    "room_name": room.name,
                    "start_time": current_time,
                    "end_time": current_time + duration,
                    "duration_minutes": duration_minutes,
                    "has_all_devices": has_all_devices,
                    "available_device_ids": available_devices,
                }
            )

    return slots
