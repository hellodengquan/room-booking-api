from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List, Optional, Dict

from app.database import get_db
from app.dependencies import get_current_active_user, require_admin_permission
from app.models.models import (
    User,
    NotificationStatus,
    Notification,
    TenantConfig,
    ABTestExperiment,
    ScoreCalibrationSample,
    SuggestionScoreLevel,
    CancellationAuditSnapshot,
    CoverageSLAConfig,
)
from app.services.advanced_service import (
    get_user_notifications,
    mark_notification_read,
    generate_dst_notifications,
    get_ab_test_variant,
    get_tenant_config,
    set_tenant_config,
    get_approval_timeout_by_tenant,
    add_calibration_sample,
    get_calibration_stats,
    create_cancellation_snapshot,
    cleanup_expired_snapshots,
    get_coverage_sla_configs,
    parse_module_coverage_targets,
    init_coverage_sla_configs,
    init_ab_test_experiments,
)
from app.config import settings

router = APIRouter(prefix="/advanced", tags=["高级功能"])


@router.get("/notifications")
async def list_notifications(
    status: Optional[str] = None,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    status_enum = NotificationStatus(status) if status else None
    notifications = get_user_notifications(db, current_user.id, status_enum, limit)
    return notifications


@router.post("/notifications/{notification_id}/read")
async def read_notification(
    notification_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    success = mark_notification_read(db, notification_id, current_user.id)
    if not success:
        raise HTTPException(status_code=404, detail="通知不存在")
    return {"success": True}


@router.post("/notifications/dst/generate")
async def generate_dst_notifications_endpoint(
    timezone: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_permission),
):
    count = generate_dst_notifications(db, timezone)
    return {"success": True, "generated_count": count}


@router.get("/ab-test/variant")
async def get_my_ab_test_variant(
    experiment_name: str = "suggestion_weights",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    variant, weights = get_ab_test_variant(db, current_user.id, experiment_name)
    return {
        "experiment": experiment_name,
        "variant": variant,
        "weights": weights,
        "ab_test_enabled": settings.AB_TEST_ENABLED,
    }


@router.get("/ab-test/experiments")
async def list_ab_test_experiments(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_permission),
):
    experiments = db.query(ABTestExperiment).all()
    return experiments


@router.post("/ab-test/experiments/init")
async def initialize_ab_tests(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_permission),
):
    experiments = init_ab_test_experiments(db)
    return {"success": True, "initialized": len(experiments)}


@router.get("/tenant-config/{tenant_id}")
async def get_tenant_config_endpoint(
    tenant_id: str,
    config_key: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_permission),
):
    value = get_tenant_config(db, tenant_id, config_key)
    return {"tenant_id": tenant_id, "config_key": config_key, "value": value}


@router.post("/tenant-config/{tenant_id}")
async def set_tenant_config_endpoint(
    tenant_id: str,
    config_key: str,
    config_value: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_permission),
):
    config = set_tenant_config(db, tenant_id, config_key, config_value)
    return config


@router.get("/tenant-config/{tenant_id}/approval-timeout")
async def get_tenant_approval_timeout(
    tenant_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_permission),
):
    config = get_approval_timeout_by_tenant(db, tenant_id)
    return {"tenant_id": tenant_id, **config}


@router.post("/calibration/samples")
async def add_calibration_sample_endpoint(
    original_score: float,
    adjusted_score: Optional[float] = None,
    score_level: Optional[str] = None,
    user_feedback: Optional[str] = None,
    booking_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    level_enum = SuggestionScoreLevel(score_level) if score_level else None
    sample = add_calibration_sample(
        db,
        original_score=original_score,
        adjusted_score=adjusted_score,
        score_level=level_enum,
        user_feedback=user_feedback,
        booking_id=booking_id,
    )
    return sample


@router.get("/calibration/stats")
async def get_calibration_statistics(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_permission),
):
    stats = get_calibration_stats(db)
    return stats


@router.post("/cancellation-snapshots/cleanup")
async def cleanup_snapshots_endpoint(
    retention_days: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_permission),
):
    deleted_count = cleanup_expired_snapshots(db, retention_days)
    return {"success": True, "deleted_count": deleted_count}


@router.post("/cancellation-snapshots/{booking_id}")
async def create_cancellation_snapshot_endpoint(
    booking_id: int,
    request_id: Optional[int] = None,
    snapshot_type: str = "cancellation",
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_permission),
):
    try:
        snapshot = create_cancellation_snapshot(db, booking_id, request_id, snapshot_type)
        return snapshot
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/coverage-sla/configs")
async def get_coverage_sla_endpoint(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_permission),
):
    configs = get_coverage_sla_configs(db)
    targets = parse_module_coverage_targets()
    return {
        "configs": configs,
        "configured_targets": targets,
        "global_target": settings.COVERAGE_SLA_TARGET,
    }


@router.post("/coverage-sla/init")
async def init_coverage_sla_endpoint(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_permission),
):
    configs = init_coverage_sla_configs(db)
    return {"success": True, "initialized": len(configs)}


@router.get("/device-bonus/config")
async def get_device_bonus_config(
    current_user: User = Depends(get_current_active_user),
):
    return {
        "enabled": settings.DEVICE_BONUS_CAP_ENABLED,
        "base_cap": settings.DEVICE_BONUS_BASE_CAP,
        "cap_per_device": settings.DEVICE_BONUS_CAP_PER_DEVICE,
        "max_cap": settings.DEVICE_BONUS_MAX_CAP,
        "per_device_weight": settings.DEVICE_MATCH_WEIGHT_PER_DEVICE,
    }
