from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app.database import get_db
from app.dependencies import get_current_active_user, require_admin_permission
from app.models.models import User, CancellationRequest, CancellationRequestStatus
from app.schemas.schemas import (
    CancellationRequestCreate,
    CancellationRequestResponse,
    RollbackRequest,
    RollbackResponse,
    CancellationAuditLogResponse,
)
from app.services.booking_service import (
    create_cancellation_request,
    approve_cancellation,
    rollback_cancellation,
)

router = APIRouter(prefix="/cancellations", tags=["取消审批"])


@router.post("", response_model=CancellationRequestResponse, status_code=201)
async def create_cancellation_request_route(
    request_in: CancellationRequestCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    request = create_cancellation_request(
        db,
        current_user.id,
        request_in.booking_ids,
        request_in.reason,
        request_in.cancellation_type,
        request_in.params,
    )
    return request


@router.get("/my", response_model=List[CancellationRequestResponse])
async def get_my_cancellation_requests(
    status: CancellationRequestStatus = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    query = db.query(CancellationRequest).filter(
        CancellationRequest.requester_id == current_user.id
    )
    if status:
        query = query.filter(CancellationRequest.status == status)
    return query.order_by(CancellationRequest.created_at.desc()).all()


@router.get("/pending", response_model=List[CancellationRequestResponse])
async def get_pending_requests(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_permission),
):
    return (
        db.query(CancellationRequest)
        .filter(CancellationRequest.status == CancellationRequestStatus.PENDING)
        .order_by(CancellationRequest.created_at.desc())
        .all()
    )


@router.get("/{request_id}", response_model=CancellationRequestResponse)
async def get_cancellation_request(
    request_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    request = (
        db.query(CancellationRequest)
        .filter(CancellationRequest.id == request_id)
        .first()
    )
    if not request:
        raise HTTPException(status_code=404, detail="取消申请不存在")

    if request.requester_id != current_user.id and current_user.permission_level != "admin":
        if not hasattr(current_user, 'permission_level'):
            from app.models.models import PermissionLevel
            if current_user.permission_level != PermissionLevel.ADMIN:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="无权查看此取消申请",
                )

    return request


@router.post("/{request_id}/approve")
async def approve_cancellation_request(
    request_id: int,
    approval_reason: str = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_permission),
):
    success, message, cancelled_ids = approve_cancellation(
        db, request_id, current_user.id, approve=True, approval_reason=approval_reason
    )
    if not success:
        raise HTTPException(status_code=400, detail=message)
    return {"success": True, "message": message, "cancelled_ids": cancelled_ids}


@router.post("/{request_id}/reject")
async def reject_cancellation_request(
    request_id: int,
    rejection_reason: str = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_permission),
):
    success, message, _ = approve_cancellation(
        db, request_id, current_user.id, approve=False, approval_reason=rejection_reason
    )
    if not success:
        raise HTTPException(status_code=400, detail=message)
    return {"success": True, "message": message}


@router.post("/rollback", response_model=RollbackResponse)
async def rollback_cancellation_route(
    rollback_in: RollbackRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_permission),
):
    success, message, restored_ids = rollback_cancellation(
        db, rollback_in.request_id, current_user.id, rollback_in.reason
    )
    if not success:
        raise HTTPException(status_code=400, detail=message)
    return RollbackResponse(
        success=success,
        restored_count=len(restored_ids),
        restored_ids=restored_ids,
        message=message,
    )


@router.get("/{request_id}/audit-logs", response_model=List[CancellationAuditLogResponse])
async def get_cancellation_audit_logs(
    request_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_permission),
):
    request = (
        db.query(CancellationRequest)
        .filter(CancellationRequest.id == request_id)
        .first()
    )
    if not request:
        raise HTTPException(status_code=404, detail="取消申请不存在")

    return request.audit_logs
