from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_active_user, require_admin, require_admin_permission
from app.models.models import Room, RoomDevice, Device, RoomPermission, User, PermissionLevel
from app.schemas.schemas import (
    RoomCreate,
    RoomUpdate,
    RoomResponse,
    RoomListResponse,
)

router = APIRouter(prefix="/rooms", tags=["会议室管理"])


@router.get("", response_model=List[RoomListResponse])
async def list_rooms(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    capacity_min: Optional[int] = Query(None, ge=1),
    is_active: Optional[bool] = None,
    location: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    query = db.query(Room)

    if capacity_min is not None:
        query = query.filter(Room.capacity >= capacity_min)
    if is_active is not None:
        query = query.filter(Room.is_active == is_active)
    if location:
        query = query.filter(Room.location.contains(location))

    rooms = query.offset(skip).limit(limit).all()
    return rooms


@router.get("/{room_id}", response_model=RoomResponse)
async def get_room(
    room_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="会议室不存在")
    return room


@router.post("", response_model=RoomResponse, status_code=201)
async def create_room(
    room_in: RoomCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_permission),
):
    existing_room = db.query(Room).filter(Room.name == room_in.name).first()
    if existing_room:
        raise HTTPException(
            status_code=400,
            detail="会议室名称已存在",
        )

    db_room = Room(
        name=room_in.name,
        location=room_in.location,
        capacity=room_in.capacity,
        description=room_in.description,
        is_active=room_in.is_active,
        requires_approval=room_in.requires_approval,
        min_booking_duration=room_in.min_booking_duration,
        max_booking_duration=room_in.max_booking_duration,
    )
    db.add(db_room)
    db.flush()

    if room_in.devices:
        for device_id in room_in.devices:
            device = db.query(Device).filter(Device.id == device_id).first()
            if device:
                room_device = RoomDevice(
                    room_id=db_room.id,
                    device_id=device_id,
                    is_permanent=True,
                )
                db.add(room_device)

    if room_in.permissions:
        for perm in room_in.permissions:
            user = db.query(User).filter(User.id == perm.user_id).first()
            if user:
                room_perm = RoomPermission(
                    room_id=db_room.id,
                    user_id=perm.user_id,
                    permission_level=perm.permission_level,
                )
                db.add(room_perm)

    db.commit()
    db.refresh(db_room)
    return db_room


@router.put("/{room_id}", response_model=RoomResponse)
async def update_room(
    room_id: int,
    room_in: RoomUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_permission),
):
    db_room = db.query(Room).filter(Room.id == room_id).first()
    if not db_room:
        raise HTTPException(status_code=404, detail="会议室不存在")

    update_data = room_in.model_dump(exclude_unset=True)

    if "devices" in update_data:
        device_ids = update_data.pop("devices")
        db.query(RoomDevice).filter(RoomDevice.room_id == room_id).delete()
        for device_id in device_ids:
            device = db.query(Device).filter(Device.id == device_id).first()
            if device:
                room_device = RoomDevice(
                    room_id=room_id,
                    device_id=device_id,
                    is_permanent=True,
                )
                db.add(room_device)

    for field, value in update_data.items():
        setattr(db_room, field, value)

    db.commit()
    db.refresh(db_room)
    return db_room


@router.delete("/{room_id}", status_code=204)
async def delete_room(
    room_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_permission),
):
    db_room = db.query(Room).filter(Room.id == room_id).first()
    if not db_room:
        raise HTTPException(status_code=404, detail="会议室不存在")

    db.query(RoomDevice).filter(RoomDevice.room_id == room_id).delete()
    db.query(RoomPermission).filter(RoomPermission.room_id == room_id).delete()
    db.delete(db_room)
    db.commit()
    return None


@router.post("/{room_id}/devices/{device_id}", status_code=201)
async def add_device_to_room(
    room_id: int,
    device_id: int,
    is_permanent: bool = True,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_permission),
):
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="会议室不存在")

    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(status_code=404, detail="设备不存在")

    existing = (
        db.query(RoomDevice)
        .filter(RoomDevice.room_id == room_id, RoomDevice.device_id == device_id)
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="设备已添加到该会议室")

    room_device = RoomDevice(
        room_id=room_id,
        device_id=device_id,
        is_permanent=is_permanent,
    )
    db.add(room_device)
    db.commit()
    return {"message": "设备添加成功"}


@router.delete("/{room_id}/devices/{device_id}", status_code=204)
async def remove_device_from_room(
    room_id: int,
    device_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_permission),
):
    room_device = (
        db.query(RoomDevice)
        .filter(RoomDevice.room_id == room_id, RoomDevice.device_id == device_id)
        .first()
    )
    if not room_device:
        raise HTTPException(status_code=404, detail="该会议室没有此设备")

    db.delete(room_device)
    db.commit()
    return None


@router.post("/{room_id}/permissions", status_code=201)
async def add_room_permission(
    room_id: int,
    user_id: int,
    permission_level: PermissionLevel = PermissionLevel.VIEW,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_permission),
):
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="会议室不存在")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    existing = (
        db.query(RoomPermission)
        .filter(RoomPermission.room_id == room_id, RoomPermission.user_id == user_id)
        .first()
    )
    if existing:
        existing.permission_level = permission_level
        db.commit()
        return {"message": "权限已更新"}

    room_perm = RoomPermission(
        room_id=room_id,
        user_id=user_id,
        permission_level=permission_level,
    )
    db.add(room_perm)
    db.commit()
    return {"message": "权限添加成功"}


@router.delete("/{room_id}/permissions/{user_id}", status_code=204)
async def remove_room_permission(
    room_id: int,
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_permission),
):
    room_perm = (
        db.query(RoomPermission)
        .filter(RoomPermission.room_id == room_id, RoomPermission.user_id == user_id)
        .first()
    )
    if not room_perm:
        raise HTTPException(status_code=404, detail="该用户没有此会议室的权限")

    db.delete(room_perm)
    db.commit()
    return None
