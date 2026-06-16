from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, field_validator, ConfigDict
from app.models.models import (
    RecurrenceType,
    BookingStatus,
    PermissionLevel,
    Weekday,
)


class UserBase(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    email: str = Field(..., max_length=100)
    full_name: Optional[str] = Field(None, max_length=100)
    permission_level: PermissionLevel = PermissionLevel.BOOK


class UserCreate(UserBase):
    password: str = Field(..., min_length=6, max_length=100)


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
    rooms: List[RoomListResponse]
    calendar: Dict[str, List[CalendarBooking]]


class BatchCancelRequest(BaseModel):
    booking_ids: Optional[List[int]] = None
    series_id: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    user_id: Optional[int] = None
    room_id: Optional[int] = None
    cancel_all: bool = False


class BatchCancelResponse(BaseModel):
    cancelled_count: int
    cancelled_ids: List[int]
    failed_count: int
    errors: List[Dict[str, Any]]


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    username: Optional[str] = None
