from fastapi import APIRouter, Depends, HTTPException, status, Query, Body
from sqlalchemy.orm import Session
from typing import List, Optional, Dict

from app.database import get_db
from app.dependencies import get_current_active_user, require_admin_permission, require_advanced_permission
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
    record_ab_test_result,
    compute_ab_test_confidence,
    get_tenant_config,
    set_tenant_config,
    hot_reload_tenant_configs,
    get_approval_timeout_by_tenant,
    add_calibration_sample,
    get_calibration_stats,
    detect_calibration_outliers,
    remove_calibration_outliers,
    create_cancellation_snapshot,
    cleanup_expired_snapshots,
    init_snapshot_retention_policies,
    get_snapshot_retention_policies,
    get_coverage_sla_configs,
    parse_module_coverage_targets,
    init_coverage_sla_configs,
    check_coverage_and_alert,
    get_coverage_alerts,
    resolve_coverage_alert,
    push_device_bonus_config,
    get_device_bonus_push_logs,
    record_coverage_dashboard,
    get_coverage_dashboard,
    set_advanced_permission,
    get_user_advanced_permissions,
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
    current_user: User = Depends(require_advanced_permission("notifications", "admin")),
):
    count = generate_dst_notifications(db, timezone)
    return {"success": True, "generated_count": count}


@router.get("/permissions/{user_id}")
async def get_permissions(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advanced_permission("permissions", "read")),
):
    perms = get_user_advanced_permissions(db, user_id)
    return perms


@router.post("/permissions")
async def set_permissions(
    user_id: int = Body(...),
    sub_module: str = Body(...),
    can_read: bool = Body(False),
    can_write: bool = Body(False),
    can_admin: bool = Body(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advanced_permission("permissions", "admin")),
):
    perm = set_advanced_permission(db, user_id, sub_module, can_read, can_write, can_admin)
    return perm


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


@router.post("/ab-test/results")
async def record_ab_result(
    experiment_name: str,
    variant: str,
    metric_key: str,
    metric_value: float,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    result = record_ab_test_result(db, experiment_name, variant, current_user.id, metric_key, metric_value)
    return result


@router.get("/ab-test/confidence")
async def get_ab_confidence(
    experiment_name: str = "suggestion_weights",
    metric_key: str = "suggestion_accepted",
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advanced_permission("ab_test", "read")),
):
    return compute_ab_test_confidence(db, experiment_name, metric_key)


@router.get("/ab-test/experiments")
async def list_ab_test_experiments(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advanced_permission("ab_test", "read")),
):
    experiments = db.query(ABTestExperiment).all()
    return experiments


@router.post("/ab-test/experiments/init")
async def initialize_ab_tests(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advanced_permission("ab_test", "admin")),
):
    experiments = init_ab_test_experiments(db)
    return {"success": True, "initialized": len(experiments)}


@router.get("/tenant-config/{tenant_id}")
async def get_tenant_config_endpoint(
    tenant_id: str,
    config_key: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advanced_permission("tenant_config", "read")),
):
    value = get_tenant_config(db, tenant_id, config_key)
    return {"tenant_id": tenant_id, "config_key": config_key, "value": value}


@router.post("/tenant-config/{tenant_id}")
async def set_tenant_config_endpoint(
    tenant_id: str,
    config_key: str,
    config_value: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advanced_permission("tenant_config", "write")),
):
    config = set_tenant_config(db, tenant_id, config_key, config_value, changed_by=current_user.id)
    return config


@router.post("/tenant-config/{tenant_id}/hot-reload")
async def hot_reload_tenant(
    tenant_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advanced_permission("tenant_config", "admin")),
):
    result = hot_reload_tenant_configs(db, tenant_id)
    return {"success": True, **result}


@router.get("/tenant-config/{tenant_id}/approval-timeout")
async def get_tenant_approval_timeout(
    tenant_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advanced_permission("tenant_config", "read")),
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
    current_user: User = Depends(require_advanced_permission("calibration", "read")),
):
    stats = get_calibration_stats(db)
    return stats


@router.get("/calibration/outliers")
async def detect_outliers(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advanced_permission("calibration", "read")),
):
    return detect_calibration_outliers(db)


@router.post("/calibration/outliers/remove")
async def remove_outliers(
    outlier_ids: List[int] = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advanced_permission("calibration", "admin")),
):
    deleted = remove_calibration_outliers(db, outlier_ids)
    return {"success": True, "deleted_count": deleted}


@router.post("/cancellation-snapshots/cleanup")
async def cleanup_snapshots_endpoint(
    retention_days: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advanced_permission("snapshots", "admin")),
):
    deleted_count = cleanup_expired_snapshots(db, retention_days)
    return {"success": True, "deleted_count": deleted_count}


@router.post("/cancellation-snapshots/{booking_id}")
async def create_cancellation_snapshot_endpoint(
    booking_id: int,
    request_id: Optional[int] = None,
    snapshot_type: str = "cancellation",
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advanced_permission("snapshots", "write")),
):
    try:
        snapshot = create_cancellation_snapshot(db, booking_id, request_id, snapshot_type)
        return snapshot
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/cancellation-snapshots/retention-policies")
async def get_retention_policies(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advanced_permission("snapshots", "read")),
):
    return get_snapshot_retention_policies(db)


@router.post("/cancellation-snapshots/retention-policies/init")
async def init_retention_policies(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advanced_permission("snapshots", "admin")),
):
    policies = init_snapshot_retention_policies(db)
    return {"success": True, "initialized": len(policies)}


@router.get("/coverage-sla/configs")
async def get_coverage_sla_endpoint(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advanced_permission("coverage", "read")),
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
    current_user: User = Depends(require_advanced_permission("coverage", "admin")),
):
    configs = init_coverage_sla_configs(db)
    return {"success": True, "initialized": len(configs)}


@router.post("/coverage-sla/check")
async def check_coverage(
    module_coverages: Dict[str, float] = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advanced_permission("coverage", "write")),
):
    alerts = check_coverage_and_alert(db, module_coverages)
    return {"alerts_generated": len(alerts), "alerts": alerts}


@router.get("/coverage-sla/alerts")
async def list_coverage_alerts(
    resolved: Optional[bool] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advanced_permission("coverage", "read")),
):
    return get_coverage_alerts(db, resolved)


@router.post("/coverage-sla/alerts/{alert_id}/resolve")
async def resolve_alert(
    alert_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advanced_permission("coverage", "write")),
):
    success = resolve_coverage_alert(db, alert_id)
    if not success:
        raise HTTPException(status_code=404, detail="告警不存在")
    return {"success": True}


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


@router.post("/device-bonus/push")
async def push_device_bonus(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advanced_permission("device_bonus", "admin")),
):
    log = push_device_bonus_config(db, pushed_by=current_user.id)
    return log


@router.get("/device-bonus/push-logs")
async def get_push_logs(
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advanced_permission("device_bonus", "read")),
):
    return get_device_bonus_push_logs(db, limit)


@router.get("/coverage-dashboard")
async def get_dashboard(
    module_name: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advanced_permission("coverage", "read")),
):
    return get_coverage_dashboard(db, module_name)


@router.post("/coverage-dashboard/record")
async def record_dashboard(
    module_name: str = Body(...),
    line_coverage: float = Body(...),
    branch_coverage: float = Body(0.0),
    statement_count: int = Body(0),
    covered_count: int = Body(0),
    missing_lines: str = Body(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advanced_permission("coverage", "write")),
):
    entry = record_coverage_dashboard(
        db, module_name, line_coverage, branch_coverage, statement_count, covered_count, missing_lines
    )
    return entry
