from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import func
import hashlib
import json
import math
import logging

from app.models.models import (
    Notification,
    NotificationType,
    NotificationStatus,
    DelegationAuditLog,
    BookingDelegation,
    ABTestExperiment,
    ABTestVariant,
    ABTestResult,
    TenantConfig,
    TenantConfigAudit,
    ScoreCalibrationSample,
    SuggestionScoreLevel,
    CancellationAuditSnapshot,
    Booking,
    CancellationRequest,
    CancellationAuditLog,
    CoverageSLAConfig,
    CoverageAlert,
    CoverageDashboard,
    AdvancedPermission,
    SnapshotRetentionPolicy,
    DeviceBonusPushLog,
    User,
)
from app.config import settings

logger = logging.getLogger(__name__)

_tenant_config_cache: Dict[str, Tuple[datetime, object]] = {}


def create_notification(
    db: Session,
    user_id: int,
    title: str,
    content: str,
    notification_type: NotificationType,
    related_id: Optional[int] = None,
    related_type: Optional[str] = None,
) -> Notification:
    notification = Notification(
        user_id=user_id,
        title=title,
        content=content,
        notification_type=notification_type,
        related_id=related_id,
        related_type=related_type,
    )
    db.add(notification)
    db.commit()
    db.refresh(notification)
    return notification


def get_user_notifications(
    db: Session,
    user_id: int,
    status: Optional[NotificationStatus] = None,
    limit: int = 50,
) -> List[Notification]:
    query = db.query(Notification).filter(Notification.user_id == user_id)
    if status:
        query = query.filter(Notification.status == status)
    return query.order_by(Notification.created_at.desc()).limit(limit).all()


def mark_notification_read(db: Session, notification_id: int, user_id: int) -> bool:
    notification = (
        db.query(Notification)
        .filter(Notification.id == notification_id, Notification.user_id == user_id)
        .first()
    )
    if not notification:
        return False
    notification.status = NotificationStatus.READ
    notification.read_at = datetime.utcnow()
    db.commit()
    return True


def generate_dst_notifications(db: Session, timezone: str = None) -> int:
    if not settings.DST_NOTIFICATION_ENABLED:
        return 0

    import pytz
    from app.routers.calendar import _is_dst_transition_day

    target_tz = timezone or settings.DEFAULT_TIMEZONE
    days_before = settings.DST_NOTIFICATION_DAYS_BEFORE

    count = 0
    today = datetime.now()
    check_date = today + timedelta(days=days_before)
    result = _is_dst_transition_day(check_date, target_tz)

    if result.get("is_dst_transition"):
        transition_type = result.get("transition_type", "unknown")
        users = db.query(User).filter(User.is_active == True).all()

        for user in users:
            title = "夏令时切换提醒"
            if transition_type == "spring_forward":
                content = f"提醒：{check_date.strftime('%Y-%m-%d')} 将进入夏令时，时钟会拨快 1 小时，请留意您的会议时间。"
            elif transition_type == "fall_back":
                content = f"提醒：{check_date.strftime('%Y-%m-%d')} 将退出夏令时，时钟会拨慢 1 小时，请留意您的会议时间。"
            else:
                content = f"提醒：{check_date.strftime('%Y-%m-%d')} 有时区调整，请留意您的会议时间。"

            existing = (
                db.query(Notification)
                .filter(
                    Notification.user_id == user.id,
                    Notification.notification_type == NotificationType.DST_REMINDER,
                    Notification.related_type == "dst_transition",
                )
                .first()
            )
            if not existing:
                create_notification(
                    db,
                    user_id=user.id,
                    title=title,
                    content=content,
                    notification_type=NotificationType.DST_REMINDER,
                    related_type="dst_transition",
                )
                count += 1

    return count


def log_delegation_audit(
    db: Session,
    delegation_id: int,
    action_type: str,
    actor_id: int,
    old_value: Optional[Dict] = None,
    new_value: Optional[Dict] = None,
    reason: Optional[str] = None,
) -> DelegationAuditLog:
    audit_log = DelegationAuditLog(
        delegation_id=delegation_id,
        action_type=action_type,
        actor_id=actor_id,
        old_value=old_value,
        new_value=new_value,
        reason=reason,
    )
    db.add(audit_log)
    db.commit()
    db.refresh(audit_log)
    return audit_log


def get_delegation_audit_logs(
    db: Session,
    delegation_id: int,
) -> List[DelegationAuditLog]:
    return (
        db.query(DelegationAuditLog)
        .filter(DelegationAuditLog.delegation_id == delegation_id)
        .order_by(DelegationAuditLog.created_at.desc())
        .all()
    )


def get_ab_test_variant(
    db: Session,
    user_id: int,
    experiment_name: str = "suggestion_weights",
) -> Tuple[str, Dict]:
    experiment = (
        db.query(ABTestExperiment)
        .filter(
            ABTestExperiment.name == experiment_name,
            ABTestExperiment.is_active == True,
        )
        .first()
    )

    if not experiment or not settings.AB_TEST_ENABLED:
        default_variant = settings.AB_TEST_DEFAULT_VARIANT
        default_weights = {
            "time": settings.SUGGESTION_SCORE_WEIGHT_TIME,
            "room": settings.SUGGESTION_SCORE_WEIGHT_ROOM,
            "device": settings.SUGGESTION_SCORE_WEIGHT_DEVICE,
        }
        return default_variant, default_weights

    variants = experiment.variants or {}
    traffic_split = experiment.traffic_split or {}

    hash_input = f"{user_id}-{experiment_name}"
    hash_val = int(hashlib.md5(hash_input.encode()).hexdigest(), 16)
    bucket = hash_val % 100

    cumulative = 0
    assigned_variant = settings.AB_TEST_DEFAULT_VARIANT
    for variant_name, percentage in traffic_split.items():
        cumulative += percentage
        if bucket < cumulative:
            assigned_variant = variant_name
            break

    variant_weights = variants.get(assigned_variant, {})
    return assigned_variant, variant_weights


def record_ab_test_result(
    db: Session,
    experiment_name: str,
    variant: str,
    user_id: int,
    metric_key: str,
    metric_value: float,
) -> ABTestResult:
    result = ABTestResult(
        experiment_name=experiment_name,
        variant=variant,
        user_id=user_id,
        metric_key=metric_key,
        metric_value=metric_value,
    )
    db.add(result)
    db.commit()
    db.refresh(result)
    return result


def compute_ab_test_confidence(
    db: Session,
    experiment_name: str,
    metric_key: str = "suggestion_accepted",
) -> Dict:
    results = (
        db.query(ABTestResult)
        .filter(
            ABTestResult.experiment_name == experiment_name,
            ABTestResult.metric_key == metric_key,
        )
        .all()
    )

    variant_data: Dict[str, List[float]] = {}
    for r in results:
        if r.variant not in variant_data:
            variant_data[r.variant] = []
        variant_data[r.variant].append(r.metric_value)

    min_samples = settings.AB_TEST_MIN_SAMPLE_SIZE
    confidence_level = settings.AB_TEST_CONFIDENCE_LEVEL
    z_score = {0.90: 1.645, 0.95: 1.96, 0.99: 2.576}.get(confidence_level, 1.96)

    variant_stats = {}
    for variant, values in variant_data.items():
        n = len(values)
        mean = sum(values) / n if n > 0 else 0
        variance = sum((v - mean) ** 2 for v in values) / n if n > 0 else 0
        std = math.sqrt(variance)
        se = std / math.sqrt(n) if n > 0 else 0
        margin = z_score * se

        variant_stats[variant] = {
            "sample_size": n,
            "mean": mean,
            "std": std,
            "confidence_interval": [mean - margin, mean + margin],
            "meets_minimum": n >= min_samples,
        }

    is_significant = False
    variant_names = list(variant_stats.keys())
    if len(variant_names) >= 2:
        v1, v2 = variant_names[0], variant_names[1]
        s1, s2 = variant_stats[v1], variant_stats[v2]
        if s1["meets_minimum"] and s2["meets_minimum"]:
            ci1 = s1["confidence_interval"]
            ci2 = s2["confidence_interval"]
            overlap = ci1[1] >= ci2[0] and ci2[1] >= ci1[0]
            is_significant = not overlap

    return {
        "experiment": experiment_name,
        "metric": metric_key,
        "variant_stats": variant_stats,
        "min_sample_size": min_samples,
        "confidence_level": confidence_level,
        "is_significant": is_significant,
        "total_results": len(results),
    }


def get_tenant_config(
    db: Session,
    tenant_id: str,
    config_key: str,
    default_value=None,
):
    cache_key = f"{tenant_id}:{config_key}"
    if cache_key in _tenant_config_cache:
        cached_at, cached_val = _tenant_config_cache[cache_key]
        if datetime.utcnow() - cached_at < timedelta(seconds=settings.TENANT_CONFIG_CACHE_TTL_SECONDS):
            return cached_val

    config = (
        db.query(TenantConfig)
        .filter(
            TenantConfig.tenant_id == tenant_id,
            TenantConfig.config_key == config_key,
        )
        .first()
    )
    value = config.config_value if config else default_value
    _tenant_config_cache[cache_key] = (datetime.utcnow(), value)
    return value


def set_tenant_config(
    db: Session,
    tenant_id: str,
    config_key: str,
    config_value,
    changed_by: Optional[int] = None,
) -> TenantConfig:
    config = (
        db.query(TenantConfig)
        .filter(
            TenantConfig.tenant_id == tenant_id,
            TenantConfig.config_key == config_key,
        )
        .first()
    )

    old_value = None
    if config:
        old_value = config.config_value
        config.config_value = config_value
    else:
        config = TenantConfig(
            tenant_id=tenant_id,
            config_key=config_key,
            config_value=config_value,
        )
        db.add(config)

    audit = TenantConfigAudit(
        tenant_id=tenant_id,
        config_key=config_key,
        old_value=old_value,
        new_value=config_value,
        changed_by=changed_by,
    )
    db.add(audit)

    db.commit()
    db.refresh(config)

    cache_key = f"{tenant_id}:{config_key}"
    _tenant_config_cache[cache_key] = (datetime.utcnow(), config_value)

    return config


def hot_reload_tenant_configs(db: Session, tenant_id: str) -> Dict[str, int]:
    _tenant_config_cache.pop(tenant_id, None)
    count = 0
    for key in list(_tenant_config_cache.keys()):
        if key.startswith(f"{tenant_id}:"):
            _tenant_config_cache.pop(key)
            count += 1

    configs = db.query(TenantConfig).filter(TenantConfig.tenant_id == tenant_id).all()
    for config in configs:
        cache_key = f"{tenant_id}:{config.config_key}"
        _tenant_config_cache[cache_key] = (datetime.utcnow(), config.config_value)
        count += 1

    return {"tenant_id": tenant_id, "reloaded_keys": count}


def get_approval_timeout_by_tenant(
    db: Session,
    tenant_id: str,
) -> Dict:
    timeout_hours = get_tenant_config(
        db, tenant_id, "cancellation_approval_timeout_hours",
        settings.CANCELLATION_APPROVAL_TIMEOUT_HOURS
    )
    timeout_action = get_tenant_config(
        db, tenant_id, "cancellation_approval_timeout_action",
        settings.CANCELLATION_APPROVAL_TIMEOUT_ACTION
    )
    return {
        "timeout_hours": timeout_hours,
        "timeout_action": timeout_action,
    }


def add_calibration_sample(
    db: Session,
    original_score: float,
    adjusted_score: Optional[float] = None,
    score_level: Optional[SuggestionScoreLevel] = None,
    user_feedback: Optional[str] = None,
    booking_id: Optional[int] = None,
    features: Optional[Dict] = None,
) -> ScoreCalibrationSample:
    sample = ScoreCalibrationSample(
        booking_id=booking_id,
        original_score=original_score,
        adjusted_score=adjusted_score,
        score_level=score_level,
        user_feedback=user_feedback,
        features=features,
    )
    db.add(sample)
    db.commit()
    db.refresh(sample)
    return sample


def detect_calibration_outliers(db: Session) -> Dict:
    samples = db.query(ScoreCalibrationSample).all()
    if not samples:
        return {"total": 0, "outliers": [], "clean_count": 0}

    scores = [s.original_score for s in samples]
    method = settings.CALIBRATION_OUTLIER_METHOD
    threshold = settings.CALIBRATION_OUTLIER_THRESHOLD
    outlier_ids = []

    if method == "iqr":
        sorted_scores = sorted(scores)
        n = len(sorted_scores)
        q1 = sorted_scores[n // 4]
        q3 = sorted_scores[3 * n // 4]
        iqr = q3 - q1
        lower = q1 - threshold * iqr
        upper = q3 + threshold * iqr
        for s in samples:
            if s.original_score < lower or s.original_score > upper:
                outlier_ids.append(s.id)
    elif method == "zscore":
        mean = sum(scores) / len(scores)
        std = math.sqrt(sum((x - mean) ** 2 for x in scores) / len(scores))
        for s in samples:
            z = abs(s.original_score - mean) / std if std > 0 else 0
            if z > threshold:
                outlier_ids.append(s.id)

    return {
        "total": len(samples),
        "outlier_ids": outlier_ids,
        "outlier_count": len(outlier_ids),
        "clean_count": len(samples) - len(outlier_ids),
        "method": method,
        "threshold": threshold,
    }


def remove_calibration_outliers(db: Session, outlier_ids: List[int]) -> int:
    deleted = 0
    for oid in outlier_ids:
        sample = db.query(ScoreCalibrationSample).filter(ScoreCalibrationSample.id == oid).first()
        if sample:
            db.delete(sample)
            deleted += 1
    db.commit()
    return deleted


def get_calibration_stats(db: Session) -> Dict:
    samples = db.query(ScoreCalibrationSample).all()
    if not samples:
        return {"total_samples": 0}

    total = len(samples)
    scores = [s.original_score for s in samples]
    avg_score = sum(scores) / total

    level_counts = {}
    for sample in samples:
        if sample.score_level:
            level = sample.score_level.value
            level_counts[level] = level_counts.get(level, 0) + 1

    feedback_counts = {}
    for sample in samples:
        if sample.user_feedback:
            feedback_counts[sample.user_feedback] = feedback_counts.get(sample.user_feedback, 0) + 1

    return {
        "total_samples": total,
        "average_score": avg_score,
        "level_distribution": level_counts,
        "feedback_distribution": feedback_counts,
    }


def create_cancellation_snapshot(
    db: Session,
    booking_id: int,
    request_id: Optional[int] = None,
    snapshot_type: str = "cancellation",
) -> CancellationAuditSnapshot:
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise ValueError(f"Booking {booking_id} not found")

    audit_logs = (
        db.query(CancellationAuditLog)
        .filter(CancellationAuditLog.booking_id == booking_id)
        .all()
    )
    audit_log_ids = [log.id for log in audit_logs]

    booking_snapshot = {
        "id": booking.id,
        "room_id": booking.room_id,
        "user_id": booking.user_id,
        "title": booking.title,
        "start_time": booking.start_time.isoformat() if booking.start_time else None,
        "end_time": booking.end_time.isoformat() if booking.end_time else None,
        "status": booking.status.value if booking.status else None,
        "attendee_count": booking.attendee_count,
        "description": booking.description,
        "recurrence_type": booking.recurrence_type.value if booking.recurrence_type else None,
        "series_id": booking.series_id,
        "delegation_id": booking.delegation_id,
        "created_at": booking.created_at.isoformat() if booking.created_at else None,
    }

    snapshot = CancellationAuditSnapshot(
        snapshot_date=datetime.utcnow(),
        booking_id=booking_id,
        booking_snapshot=booking_snapshot,
        request_id=request_id,
        audit_log_ids=audit_log_ids,
        snapshot_type=snapshot_type,
    )
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    return snapshot


def cleanup_expired_snapshots(db: Session, retention_days: int = None) -> int:
    if retention_days is None:
        retention_days = settings.CANCELLATION_AUDIT_SNAPSHOT_RETENTION_DAYS

    cutoff_date = datetime.utcnow() - timedelta(days=retention_days)
    expired = (
        db.query(CancellationAuditSnapshot)
        .filter(CancellationAuditSnapshot.created_at < cutoff_date)
        .all()
    )
    count = len(expired)
    for snapshot in expired:
        db.delete(snapshot)
    db.commit()
    return count


def init_snapshot_retention_policies(db: Session) -> List[SnapshotRetentionPolicy]:
    windows = settings.SNAPSHOT_RETENTION_WINDOW_DAYS
    policies = []
    for w in windows.split(","):
        w = w.strip()
        if w.isdigit():
            days = int(w)
            existing = (
                db.query(SnapshotRetentionPolicy)
                .filter(SnapshotRetentionPolicy.window_days == days)
                .first()
            )
            if not existing:
                if days <= 30:
                    action = "archive"
                    name = f"短期归档 ({days}天)"
                elif days <= 90:
                    action = "compress"
                    name = f"中期压缩 ({days}天)"
                else:
                    action = "delete"
                    name = f"长期清理 ({days}天)"
                policy = SnapshotRetentionPolicy(
                    window_days=days,
                    policy_name=name,
                    action=action,
                )
                db.add(policy)
                policies.append(policy)
    db.commit()
    return policies


def get_snapshot_retention_policies(db: Session) -> List[SnapshotRetentionPolicy]:
    return db.query(SnapshotRetentionPolicy).filter(SnapshotRetentionPolicy.is_active == True).all()


def get_coverage_sla_configs(db: Session) -> List[CoverageSLAConfig]:
    return db.query(CoverageSLAConfig).filter(CoverageSLAConfig.is_active == True).all()


def parse_module_coverage_targets() -> Dict[str, float]:
    module_str = settings.COVERAGE_SLA_MODULES
    targets = {}
    if module_str:
        for item in module_str.split(","):
            if ":" in item:
                module, target = item.strip().split(":")
                targets[module.strip()] = float(target)
    return targets


def init_coverage_sla_configs(db: Session) -> List[CoverageSLAConfig]:
    targets = parse_module_coverage_targets()
    configs = []
    for module_name, target in targets.items():
        existing = (
            db.query(CoverageSLAConfig)
            .filter(CoverageSLAConfig.module_name == module_name)
            .first()
        )
        if not existing:
            config = CoverageSLAConfig(
                module_name=module_name,
                target_coverage=target,
                description=f"{module_name} 模块覆盖率目标",
            )
            db.add(config)
            configs.append(config)
    db.commit()
    return configs


def check_coverage_and_alert(db: Session, module_coverages: Dict[str, float]) -> List[CoverageAlert]:
    alerts = []
    sla_configs = db.query(CoverageSLAConfig).filter(CoverageSLAConfig.is_active == True).all()
    channel = settings.COVERAGE_SLA_ALERT_CHANNEL
    webhook_url = settings.COVERAGE_SLA_WEBHOOK_URL

    for sla in sla_configs:
        current = module_coverages.get(sla.module_name, 0.0)
        if current < sla.target_coverage:
            deficit = sla.target_coverage - current
            if deficit >= 20:
                level = "critical"
            elif deficit >= 10:
                level = "warning"
            else:
                level = "info"

            alert = CoverageAlert(
                module_name=sla.module_name,
                current_coverage=current,
                target_coverage=sla.target_coverage,
                alert_level=level,
                channel=channel,
                message=f"{sla.module_name} 覆盖率 {current:.1f}% 低于目标 {sla.target_coverage:.1f}%",
            )
            db.add(alert)
            alerts.append(alert)

            if channel == "log":
                logger.warning(f"[Coverage Alert] {alert.message} (level={level})")
            elif channel == "webhook" and webhook_url:
                try:
                    import urllib.request
                    data = json.dumps({
                        "module": sla.module_name,
                        "current": current,
                        "target": sla.target_coverage,
                        "level": level,
                    }).encode()
                    req = urllib.request.Request(webhook_url, data=data, headers={"Content-Type": "application/json"})
                    urllib.request.urlopen(req, timeout=5)
                except Exception as e:
                    logger.error(f"Webhook alert failed: {e}")
            elif channel == "notification":
                admins = db.query(User).filter(User.permission_level == "admin", User.is_active == True).all()
                for admin in admins:
                    create_notification(
                        db, admin.id,
                        title=f"覆盖率告警: {sla.module_name}",
                        content=alert.message,
                        notification_type=NotificationType.SYSTEM,
                        related_type="coverage_alert",
                    )

    db.commit()
    return alerts


def get_coverage_alerts(db: Session, resolved: Optional[bool] = None) -> List[CoverageAlert]:
    query = db.query(CoverageAlert)
    if resolved is not None:
        query = query.filter(CoverageAlert.is_resolved == resolved)
    return query.order_by(CoverageAlert.created_at.desc()).all()


def resolve_coverage_alert(db: Session, alert_id: int) -> bool:
    alert = db.query(CoverageAlert).filter(CoverageAlert.id == alert_id).first()
    if not alert:
        return False
    alert.is_resolved = True
    alert.resolved_at = datetime.utcnow()
    db.commit()
    return True


def push_device_bonus_config(db: Session, pushed_by: int) -> DeviceBonusPushLog:
    config_snapshot = {
        "enabled": settings.DEVICE_BONUS_CAP_ENABLED,
        "base_cap": settings.DEVICE_BONUS_BASE_CAP,
        "cap_per_device": settings.DEVICE_BONUS_CAP_PER_DEVICE,
        "max_cap": settings.DEVICE_BONUS_MAX_CAP,
        "per_device_weight": settings.DEVICE_MATCH_WEIGHT_PER_DEVICE,
    }
    strategy = settings.DEVICE_BONUS_PUSH_STRATEGY

    affected = db.query(User).filter(User.is_active == True).count()

    log = DeviceBonusPushLog(
        config_snapshot=config_snapshot,
        strategy=strategy,
        pushed_by=pushed_by,
        affected_users=affected,
    )
    db.add(log)
    db.commit()
    db.refresh(log)

    if strategy in ("on_change", "immediate"):
        admins = db.query(User).filter(User.permission_level == "admin", User.is_active == True).all()
        for admin in admins:
            create_notification(
                db, admin.id,
                title="设备权重配置已推送",
                content=f"device-bonus 配置已更新并推送，策略: {strategy}",
                notification_type=NotificationType.SYSTEM,
                related_id=log.id,
                related_type="device_bonus_push",
            )

    return log


def get_device_bonus_push_logs(db: Session, limit: int = 20) -> List[DeviceBonusPushLog]:
    return db.query(DeviceBonusPushLog).order_by(DeviceBonusPushLog.created_at.desc()).limit(limit).all()


def record_coverage_dashboard(
    db: Session,
    module_name: str,
    line_coverage: float,
    branch_coverage: float = 0.0,
    statement_count: int = 0,
    covered_count: int = 0,
    missing_lines: str = "",
) -> CoverageDashboard:
    entry = CoverageDashboard(
        module_name=module_name,
        line_coverage=line_coverage,
        branch_coverage=branch_coverage,
        statement_count=statement_count,
        covered_count=covered_count,
        missing_lines=missing_lines,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def get_coverage_dashboard(db: Session, module_name: Optional[str] = None) -> Dict:
    query = db.query(CoverageDashboard)
    if module_name:
        query = query.filter(CoverageDashboard.module_name == module_name)

    entries = query.order_by(CoverageDashboard.recorded_at.desc()).limit(100).all()

    modules: Dict[str, List] = {}
    for entry in entries:
        if entry.module_name not in modules:
            modules[entry.module_name] = []
        modules[entry.module_name].append({
            "line_coverage": entry.line_coverage,
            "branch_coverage": entry.branch_coverage,
            "statement_count": entry.statement_count,
            "covered_count": entry.covered_count,
            "recorded_at": entry.recorded_at.isoformat() if entry.recorded_at else None,
        })

    summary = {}
    for mod, records in modules.items():
        if records:
            latest = records[0]
            summary[mod] = {
                "latest_coverage": latest["line_coverage"],
                "latest_branch": latest["branch_coverage"],
                "total_statements": latest["statement_count"],
                "total_covered": latest["covered_count"],
                "history_count": len(records),
            }

    return {
        "enabled": settings.COVERAGE_DASHBOARD_ENABLED,
        "modules": summary,
        "total_modules": len(summary),
    }


def set_advanced_permission(
    db: Session,
    user_id: int,
    sub_module: str,
    can_read: bool = False,
    can_write: bool = False,
    can_admin: bool = False,
) -> AdvancedPermission:
    perm = (
        db.query(AdvancedPermission)
        .filter(
            AdvancedPermission.user_id == user_id,
            AdvancedPermission.sub_module == sub_module,
        )
        .first()
    )
    if perm:
        perm.can_read = can_read
        perm.can_write = can_write
        perm.can_admin = can_admin
    else:
        perm = AdvancedPermission(
            user_id=user_id,
            sub_module=sub_module,
            can_read=can_read,
            can_write=can_write,
            can_admin=can_admin,
        )
        db.add(perm)
    db.commit()
    db.refresh(perm)
    return perm


def get_user_advanced_permissions(db: Session, user_id: int) -> List[AdvancedPermission]:
    return db.query(AdvancedPermission).filter(AdvancedPermission.user_id == user_id).all()


def init_ab_test_experiments(db: Session) -> List[ABTestExperiment]:
    experiments_data = [
        {
            "name": "suggestion_weights",
            "description": "替代建议评分权重 A/B 测试",
            "variants": {
                "control": {
                    "time": 0.4,
                    "room": 0.3,
                    "device": 0.3,
                },
                "variant_a": {
                    "time": 0.5,
                    "room": 0.3,
                    "device": 0.2,
                },
                "variant_b": {
                    "time": 0.3,
                    "room": 0.4,
                    "device": 0.3,
                },
            },
            "traffic_split": {
                "control": 40,
                "variant_a": 30,
                "variant_b": 30,
            },
        }
    ]

    experiments = []
    for exp_data in experiments_data:
        existing = (
            db.query(ABTestExperiment)
            .filter(ABTestExperiment.name == exp_data["name"])
            .first()
        )
        if not existing:
            exp = ABTestExperiment(**exp_data)
            db.add(exp)
            experiments.append(exp)
    db.commit()
    return experiments
