from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from sqlalchemy.orm import Session
import hashlib

from app.models.models import (
    Notification,
    NotificationType,
    NotificationStatus,
    DelegationAuditLog,
    BookingDelegation,
    ABTestExperiment,
    ABTestVariant,
    TenantConfig,
    ScoreCalibrationSample,
    SuggestionScoreLevel,
    CancellationAuditSnapshot,
    Booking,
    CancellationRequest,
    CancellationAuditLog,
    CoverageSLAConfig,
    User,
)
from app.config import settings


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


def get_tenant_config(
    db: Session,
    tenant_id: str,
    config_key: str,
    default_value=None,
):
    config = (
        db.query(TenantConfig)
        .filter(
            TenantConfig.tenant_id == tenant_id,
            TenantConfig.config_key == config_key,
        )
        .first()
    )
    return config.config_value if config else default_value


def set_tenant_config(
    db: Session,
    tenant_id: str,
    config_key: str,
    config_value,
) -> TenantConfig:
    config = (
        db.query(TenantConfig)
        .filter(
            TenantConfig.tenant_id == tenant_id,
            TenantConfig.config_key == config_key,
        )
        .first()
    )
    if config:
        config.config_value = config_value
    else:
        config = TenantConfig(
            tenant_id=tenant_id,
            config_key=config_key,
            config_value=config_value,
        )
        db.add(config)
    db.commit()
    db.refresh(config)
    return config


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
