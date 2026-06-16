from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, field_validator, ConfigDict
from app.models.models import (
    RecurrenceType,
    BookingStatus,
    PermissionLevel,
    Weekday,
    CancellationRequestStatus,
    SuggestionScoreLevel,
)


class UserBase(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    email: str = Field(..., max_length=100)
    full_name: Optional[str] = Field(None, max_length=100)
    permission_level: PermissionLevel = PermissionLevel.BOOK
    timezone: str = "Asia/Shanghai"


class UserCreate(UserBase):
    password: str = Field(..., min_length=6, max_length=100)


class UserUpdate(BaseModel):
    full_name: Optional[str] = Field(None, max_length=100)
    email: Optional[str] = Field(None, max_length=100)
    timezone: Optional[str] = None
    permission_level: Optional[PermissionLevel] = None


class UserResponse(UserBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class DeviceBase(BaseModel):
    name: str = Field(..., max_length=100)
    device_type: str = Field(..., max_length=50)
    description: Optional[str] = None
    is_available: bool = True


class DeviceCreate(DeviceBase):
    pass


class DeviceResponse(DeviceBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime


class RoomDeviceBase(BaseModel):
    device_id: int
    is_permanent: bool = True


class RoomDeviceCreate(RoomDeviceBase):
    pass


class RoomDeviceResponse(RoomDeviceBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    device: DeviceResponse
    created_at: datetime


class RoomPermissionBase(BaseModel):
    user_id: int
    permission_level: PermissionLevel = PermissionLevel.VIEW


class RoomPermissionCreate(RoomPermissionBase):
    pass


class RoomPermissionResponse(RoomPermissionBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user: UserResponse
    created_at: datetime


class RoomBase(BaseModel):
    name: str = Field(..., max_length=100)
    location: Optional[str] = Field(None, max_length=200)
    capacity: int = Field(..., gt=0)
    description: Optional[str] = None
    is_active: bool = True
    requires_approval: bool = False
    min_booking_duration: int = Field(30, ge=15)
    max_booking_duration: int = Field(480, ge=30)
    timezone: str = "Asia/Shanghai"


class RoomCreate(RoomBase):
    devices: Optional[List[int]] = None
    permissions: Optional[List[RoomPermissionCreate]] = None


class RoomUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    location: Optional[str] = Field(None, max_length=200)
    capacity: Optional[int] = Field(None, gt=0)
    description: Optional[str] = None
    is_active: Optional[bool] = None
    requires_approval: Optional[bool] = None
    min_booking_duration: Optional[int] = Field(None, ge=15)
    max_booking_duration: Optional[int] = Field(None, ge=30)
    timezone: Optional[str] = None
    devices: Optional[List[int]] = None


class RoomResponse(RoomBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
    room_devices: List[RoomDeviceResponse] = []
    room_permissions: List[RoomPermissionResponse] = []


class RoomListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    location: Optional[str]
    capacity: int
    is_active: bool
    requires_approval: bool
    timezone: str = "Asia/Shanghai"


class RecurrenceConfig(BaseModel):
    recurrence_type: RecurrenceType = RecurrenceType.NONE
    recurrence_end_date: Optional[datetime] = None
    recurrence_weekdays: Optional[List[int]] = None
    recurrence_interval: int = 1

    @field_validator("recurrence_weekdays")
    def validate_weekdays(cls, v):
        if v is not None:
            for day in v:
                if day < 0 or day > 6:
                    raise ValueError("Weekday must be between 0 (Monday) and 6 (Sunday)")
        return v


class BookingSkipCreate(BaseModel):
    booking_id: Optional[int] = None
    series_id: Optional[str] = None
    skip_date: datetime
    reason: Optional[str] = None


class BookingSkipResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    booking_id: int
    series_id: Optional[str]
    skip_date: datetime
    reason: Optional[str]
    skipped_by: Optional[int]
    created_at: datetime


class BookingDeviceCreate(BaseModel):
    device_id: int


class BookingBase(BaseModel):
    title: str = Field(..., max_length=200)
    description: Optional[str] = None
    room_id: int
    start_time: datetime
    end_time: datetime
    attendee_count: int = Field(1, ge=1)
    device_ids: Optional[List[int]] = None
    recurrence: Optional[RecurrenceConfig] = None
    delegate_user_id: Optional[int] = None

    @field_validator("end_time")
    def end_after_start(cls, v, values):
        if "start_time" in values.data and v <= values.data["start_time"]:
            raise ValueError("End time must be after start time")
        return v


class BookingCreate(BookingBase):
    pass


class BookingUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=200)
    description: Optional[str] = None
    room_id: Optional[int] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    attendee_count: Optional[int] = Field(None, ge=1)
    device_ids: Optional[List[int]] = None
    status: Optional[BookingStatus] = None


class ConflictInfo(BaseModel):
    booking_id: int
    title: str
    start_time: datetime
    end_time: datetime
    user_id: int
    conflict_type: str


class AlternativeSuggestion(BaseModel):
    room_id: int
    room_name: str
    start_time: datetime
    end_time: datetime
    duration_minutes: int
    score: float = 0.0
    score_level: SuggestionScoreLevel = SuggestionScoreLevel.FAIR
    score_reasons: List[str] = []
    has_required_devices: bool = True
    capacity_match: bool = True


class BookingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    room_id: int
    user_id: int
    title: str
    description: Optional[str]
    start_time: datetime
    end_time: datetime
    status: BookingStatus
    recurrence_type: RecurrenceType
    recurrence_end_date: Optional[datetime]
    recurrence_weekdays: Optional[List[int]]
    recurrence_interval: int
    series_id: Optional[str]
    attendee_count: int
    delegation_id: Optional[int]
    created_at: datetime
    updated_at: datetime
    conflicts: Optional[List[ConflictInfo]] = None
    alternatives: Optional[List[AlternativeSuggestion]] = None


class BookingListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    room_id: int
    room_name: str
    user_id: int
    user_name: str
    title: str
    start_time: datetime
    end_time: datetime
    status: BookingStatus
    attendee_count: int


class CalendarViewQuery(BaseModel):
    start_date: datetime
    end_date: datetime
    room_ids: Optional[List[int]] = None
    user_id: Optional[int] = None
    timezone: Optional[str] = None


class CalendarBooking(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    room_id: int
    title: str
    start_time: datetime
    end_time: datetime
    status: BookingStatus
    user_id: int


class CalendarDayView(BaseModel):
    date: str
    bookings: List[CalendarBooking]


class CalendarViewResponse(BaseModel):
    start_date: datetime
    end_date: datetime
    timezone: str
    rooms: List[RoomListResponse]
    calendar: Dict[str, List[CalendarBooking]]


class AvailableSlotQuery(BaseModel):
    room_id: Optional[int] = None
    room_ids: Optional[List[int]] = None
    start_date: datetime
    end_date: datetime
    duration_minutes: int = Field(60, ge=15, le=480)
    device_ids: Optional[List[int]] = None
    min_capacity: Optional[int] = None


class AvailableSlot(BaseModel):
    room_id: int
    room_name: str
    start_time: datetime
    end_time: datetime
    duration_minutes: int
    has_all_devices: bool = True
    available_device_ids: List[int] = []


class AvailableSlotsResponse(BaseModel):
    available_slots: List[AvailableSlot]
    total_count: int


class BatchCancelRequest(BaseModel):
    booking_ids: Optional[List[int]] = None
    series_id: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    user_id: Optional[int] = None
    room_id: Optional[int] = None
    cancel_all: bool = False
    reason: Optional[str] = None
    require_approval: bool = False


class BatchCancelResponse(BaseModel):
    cancelled_count: int
    cancelled_ids: List[int]
    failed_count: int
    errors: List[Dict[str, Any]]
    rollback_supported: bool = True
    audit_log_id: Optional[int] = None


class CancellationRequestCreate(BaseModel):
    booking_ids: List[int]
    reason: Optional[str] = None
    cancellation_type: str = "ids"
    params: Optional[Dict[str, Any]] = None


class CancellationRequestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    requester_id: int
    approver_id: Optional[int]
    status: CancellationRequestStatus
    reason: Optional[str]
    approval_reason: Optional[str]
    booking_ids: List[int]
    cancellation_type: str
    params: Optional[Dict[str, Any]]
    created_at: datetime
    approved_at: Optional[datetime]
    rolled_back_at: Optional[datetime]


class CancellationAuditLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    request_id: int
    booking_id: int
    original_status: BookingStatus
    new_status: BookingStatus
    action_type: str
    action_by: Optional[int]
    created_at: datetime


class BookingDelegationCreate(BaseModel):
    delegate_id: int
    room_id: Optional[int] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    reason: Optional[str] = None


class BookingDelegationUpdate(BaseModel):
    is_active: Optional[bool] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    reason: Optional[str] = None


class BookingDelegationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    delegator_id: int
    delegate_id: int
    room_id: Optional[int]
    is_active: bool
    start_date: Optional[datetime]
    end_date: Optional[datetime]
    reason: Optional[str]
    created_at: datetime
    revoked_at: Optional[datetime] = None
    revoked_by: Optional[int] = None
    revocation_reason: Optional[str] = None


class DelegationRevokeRequest(BaseModel):
    reason: Optional[str] = None


class RollbackRequest(BaseModel):
    request_id: int
    reason: Optional[str] = None


class RollbackResponse(BaseModel):
    success: bool
    restored_count: int
    restored_ids: List[int]
    message: str


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    username: Optional[str] = None


class CoverageStats(BaseModel):
    total_tests: int
    passed_tests: int
    failed_tests: int
    skipped_tests: int
    coverage_percent: float
    covered_lines: int
    missing_lines: int
    total_lines: int
