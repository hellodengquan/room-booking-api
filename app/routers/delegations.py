from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app.database import get_db
from app.dependencies import get_current_active_user
from app.models.models import User, BookingDelegation
from app.schemas.schemas import (
    BookingDelegationCreate,
    BookingDelegationUpdate,
    BookingDelegationResponse,
    DelegationRevokeRequest,
)
from app.services.booking_service import (
    create_delegation,
    get_user_delegations,
    check_delegation_permission,
)

router = APIRouter(prefix="/delegations", tags=["委托代订"])


@router.post("", response_model=BookingDelegationResponse, status_code=201)
async def create_delegation_route(
    delegation_in: BookingDelegationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    if delegation_in.delegate_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="不能委托给自己",
        )

    delegate = db.query(User).filter(User.id == delegation_in.delegate_id).first()
    if not delegate:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="被委托人不存在",
        )

    delegation = create_delegation(db, current_user.id, delegation_in)
    return delegation


@router.get("/from-me", response_model=List[BookingDelegationResponse])
async def get_my_delegations(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    return get_user_delegations(db, current_user.id, as_delegator=True)


@router.get("/to-me", response_model=List[BookingDelegationResponse])
async def get_delegations_to_me(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    return get_user_delegations(db, current_user.id, as_delegator=False)


@router.get("/{delegation_id}", response_model=BookingDelegationResponse)
async def get_delegation(
    delegation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    delegation = (
        db.query(BookingDelegation)
        .filter(BookingDelegation.id == delegation_id)
        .first()
    )
    if not delegation:
        raise HTTPException(status_code=404, detail="委托不存在")

    if (
        delegation.delegator_id != current_user.id
        and delegation.delegate_id != current_user.id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权查看此委托",
        )

    return delegation


@router.put("/{delegation_id}", response_model=BookingDelegationResponse)
async def update_delegation(
    delegation_id: int,
    delegation_in: BookingDelegationUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    delegation = (
        db.query(BookingDelegation)
        .filter(BookingDelegation.id == delegation_id)
        .first()
    )
    if not delegation:
        raise HTTPException(status_code=404, detail="委托不存在")

    if delegation.delegator_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有委托人才能修改委托",
        )

    if delegation_in.is_active is not None:
        delegation.is_active = delegation_in.is_active
    if delegation_in.start_date is not None:
        delegation.start_date = delegation_in.start_date
    if delegation_in.end_date is not None:
        delegation.end_date = delegation_in.end_date
    if delegation_in.reason is not None:
        delegation.reason = delegation_in.reason

    db.commit()
    db.refresh(delegation)
    return delegation


@router.delete("/{delegation_id}", status_code=204)
async def deactivate_delegation(
    delegation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    delegation = (
        db.query(BookingDelegation)
        .filter(BookingDelegation.id == delegation_id)
        .first()
    )
    if not delegation:
        raise HTTPException(status_code=404, detail="委托不存在")

    if delegation.delegator_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有委托人才能取消委托",
        )

    delegation.is_active = False
    db.commit()
    return None


@router.post("/{delegation_id}/revoke", response_model=BookingDelegationResponse)
async def revoke_delegation(
    delegation_id: int,
    revoke_in: DelegationRevokeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    delegation = (
        db.query(BookingDelegation)
        .filter(BookingDelegation.id == delegation_id)
        .first()
    )
    if not delegation:
        raise HTTPException(status_code=404, detail="委托不存在")

    if delegation.delegator_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有委托人才能撤销委托",
        )

    if not delegation.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="委托已处于非激活状态",
        )

    from datetime import datetime as dt

    delegation.is_active = False
    delegation.revoked_at = dt.utcnow()
    delegation.revoked_by = current_user.id
    delegation.revocation_reason = revoke_in.reason

    db.commit()
    db.refresh(delegation)
    return delegation
