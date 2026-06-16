import pytest
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.main import app
from app.database import get_db, Base
from app.dependencies import get_password_hash
from app.models.models import User, Room, Device, Booking, PermissionLevel, BookingStatus, RecurrenceType

SQLALCHEMY_DATABASE_URL = "sqlite:///./test_room_booking.db"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="function")
def db_session():
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            db_session.close()

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def test_user_id(db_session):
    hashed_pwd = get_password_hash("testpassword123")
    user = User(
        username="testuser",
        email="test@example.com",
        full_name="Test User",
        hashed_password=hashed_pwd,
        permission_level=PermissionLevel.BOOK,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    user_id = user.id
    db_session.expunge(user)
    return user_id


@pytest.fixture
def test_user(db_session, test_user_id):
    return db_session.query(User).filter(User.id == test_user_id).first()


@pytest.fixture
def test_admin_id(db_session):
    hashed_pwd = get_password_hash("adminpassword123")
    admin = User(
        username="adminuser",
        email="admin@example.com",
        full_name="Admin User",
        hashed_password=hashed_pwd,
        permission_level=PermissionLevel.ADMIN,
    )
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)
    admin_id = admin.id
    db_session.expunge(admin)
    return admin_id


@pytest.fixture
def test_admin(db_session, test_admin_id):
    return db_session.query(User).filter(User.id == test_admin_id).first()


@pytest.fixture
def test_room_id(db_session):
    room = Room(
        name="会议室A",
        location="3楼",
        capacity=10,
        description="小型会议室",
        is_active=True,
        requires_approval=False,
        min_booking_duration=30,
        max_booking_duration=480,
    )
    db_session.add(room)
    db_session.commit()
    db_session.refresh(room)
    room_id = room.id
    db_session.expunge(room)
    return room_id


@pytest.fixture
def test_room_b_id(db_session):
    room = Room(
        name="会议室B",
        location="3楼",
        capacity=20,
        description="中型会议室",
        is_active=True,
        requires_approval=False,
        min_booking_duration=30,
        max_booking_duration=480,
    )
    db_session.add(room)
    db_session.commit()
    db_session.refresh(room)
    room_id = room.id
    db_session.expunge(room)
    return room_id


@pytest.fixture
def test_device_id(db_session):
    device = Device(
        name="投影仪",
        device_type="显示设备",
        description="高清投影仪",
        is_available=True,
    )
    db_session.add(device)
    db_session.commit()
    db_session.refresh(device)
    device_id = device.id
    db_session.expunge(device)
    return device_id


@pytest.fixture
def test_room(db_session, test_room_id):
    return db_session.query(Room).filter(Room.id == test_room_id).first()


@pytest.fixture
def test_room_b(db_session, test_room_b_id):
    return db_session.query(Room).filter(Room.id == test_room_b_id).first()


@pytest.fixture
def test_device(db_session, test_device_id):
    return db_session.query(Device).filter(Device.id == test_device_id).first()


@pytest.fixture
def auth_headers(client, test_user):
    response = client.post(
        "/api/v1/auth/login",
        data={"username": "testuser", "password": "testpassword123"},
    )
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin_headers(client, test_admin):
    response = client.post(
        "/api/v1/auth/login",
        data={"username": "adminuser", "password": "adminpassword123"},
    )
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


class TestAuth:
    def test_register_user(self, client):
        response = client.post(
            "/api/v1/auth/register",
            json={
                "username": "newuser",
                "email": "new@example.com",
                "full_name": "New User",
                "password": "password123",
                "permission_level": "book",
            },
        )
        assert response.status_code == 201
        assert response.json()["username"] == "newuser"

    def test_register_duplicate_username(self, client, test_user):
        response = client.post(
            "/api/v1/auth/register",
            json={
                "username": "testuser",
                "email": "another@example.com",
                "password": "password123",
                "permission_level": "book",
            },
        )
        assert response.status_code == 400

    def test_login_success(self, client, test_user):
        response = client.post(
            "/api/v1/auth/login",
            data={"username": "testuser", "password": "testpassword123"},
        )
        assert response.status_code == 200
        assert "access_token" in response.json()

    def test_login_wrong_password(self, client, test_user):
        response = client.post(
            "/api/v1/auth/login",
            data={"username": "testuser", "password": "wrongpassword"},
        )
        assert response.status_code == 401

    def test_get_me(self, client, auth_headers):
        response = client.get("/api/v1/auth/me", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["username"] == "testuser"


class TestRooms:
    def test_create_room(self, client, admin_headers):
        response = client.post(
            "/api/v1/rooms",
            json={
                "name": "测试会议室",
                "location": "2楼",
                "capacity": 8,
                "description": "测试用会议室",
                "is_active": True,
                "requires_approval": False,
                "min_booking_duration": 30,
                "max_booking_duration": 240,
            },
            headers=admin_headers,
        )
        assert response.status_code == 201
        assert response.json()["name"] == "测试会议室"

    def test_create_room_unauthorized(self, client, auth_headers):
        response = client.post(
            "/api/v1/rooms",
            json={
                "name": "测试会议室",
                "location": "2楼",
                "capacity": 8,
            },
            headers=auth_headers,
        )
        assert response.status_code == 403

    def test_list_rooms(self, client, test_room, test_room_b, auth_headers):
        response = client.get("/api/v1/rooms", headers=auth_headers)
        assert response.status_code == 200
        assert len(response.json()) == 2

    def test_get_room(self, client, test_room_id, auth_headers):
        response = client.get(f"/api/v1/rooms/{test_room_id}", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["name"] == "会议室A"

    def test_get_nonexistent_room(self, client, auth_headers):
        response = client.get("/api/v1/rooms/999", headers=auth_headers)
        assert response.status_code == 404

    def test_update_room(self, client, test_room_id, admin_headers):
        response = client.put(
            f"/api/v1/rooms/{test_room_id}",
            json={"name": "会议室A-更新", "capacity": 15},
            headers=admin_headers,
        )
        assert response.status_code == 200
        assert response.json()["name"] == "会议室A-更新"
        assert response.json()["capacity"] == 15

    def test_delete_room(self, client, test_room_id, admin_headers):
        response = client.delete(
            f"/api/v1/rooms/{test_room_id}", headers=admin_headers
        )
        assert response.status_code == 204


class TestBookings:
    def test_create_booking(self, client, test_user, test_room, auth_headers):
        future_start = datetime.now() + timedelta(hours=2)
        future_end = future_start + timedelta(hours=1)

        response = client.post(
            "/api/v1/bookings",
            json={
                "title": "测试会议",
                "description": "测试预订",
                "room_id": test_room.id,
                "start_time": future_start.isoformat(),
                "end_time": future_end.isoformat(),
                "attendee_count": 5,
            },
            headers=auth_headers,
        )
        assert response.status_code == 201
        assert response.json()["success"] is True
        assert len(response.json()["bookings"]) == 1

    def test_create_booking_conflict(self, client, test_user, test_room, auth_headers, db_session):
        future_start = datetime.now() + timedelta(hours=2)
        future_end = future_start + timedelta(hours=1)

        existing_booking = Booking(
            room_id=test_room.id,
            user_id=test_user.id,
            title="已有会议",
            start_time=future_start,
            end_time=future_end,
            status=BookingStatus.CONFIRMED,
            recurrence_type=RecurrenceType.NONE,
        )
        db_session.add(existing_booking)
        db_session.commit()

        response = client.post(
            "/api/v1/bookings",
            json={
                "title": "冲突会议",
                "room_id": test_room.id,
                "start_time": future_start.isoformat(),
                "end_time": future_end.isoformat(),
                "attendee_count": 3,
            },
            headers=auth_headers,
        )
        assert response.status_code == 201
        assert response.json()["success"] is False
        assert len(response.json()["conflicts"]) > 0

    def test_check_conflict(self, client, test_room_id, auth_headers):
        future_start = datetime.now() + timedelta(hours=2)
        future_end = future_start + timedelta(hours=1)

        response = client.get(
            "/api/v1/bookings/check-conflict",
            params={
                "room_id": test_room_id,
                "start_time": future_start.isoformat(),
                "end_time": future_end.isoformat(),
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["has_conflict"] is False

    def test_create_recurring_booking(self, client, test_user, test_room, auth_headers):
        future_start = datetime.now() + timedelta(days=1, hours=10)
        future_end = future_start + timedelta(hours=1)

        response = client.post(
            "/api/v1/bookings",
            json={
                "title": "周例会",
                "room_id": test_room.id,
                "start_time": future_start.isoformat(),
                "end_time": future_end.isoformat(),
                "attendee_count": 5,
                "recurrence": {
                    "recurrence_type": "weekly",
                    "recurrence_end_date": (future_start + timedelta(weeks=3)).isoformat(),
                    "recurrence_interval": 1,
                },
            },
            headers=auth_headers,
        )
        assert response.status_code == 201
        assert response.json()["success"] is True
        assert len(response.json()["bookings"]) >= 3

    def test_update_booking(self, client, test_user, test_room, auth_headers, db_session):
        future_start = datetime.now() + timedelta(hours=2)
        future_end = future_start + timedelta(hours=1)

        booking = Booking(
            room_id=test_room.id,
            user_id=test_user.id,
            title="原会议",
            start_time=future_start,
            end_time=future_end,
            status=BookingStatus.CONFIRMED,
            recurrence_type=RecurrenceType.NONE,
        )
        db_session.add(booking)
        db_session.commit()

        response = client.put(
            f"/api/v1/bookings/{booking.id}",
            json={"title": "更新后的会议"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["title"] == "更新后的会议"

    def test_cancel_booking(self, client, test_user, test_room, auth_headers, db_session):
        future_start = datetime.now() + timedelta(hours=2)
        future_end = future_start + timedelta(hours=1)

        booking = Booking(
            room_id=test_room.id,
            user_id=test_user.id,
            title="待取消会议",
            start_time=future_start,
            end_time=future_end,
            status=BookingStatus.CONFIRMED,
            recurrence_type=RecurrenceType.NONE,
        )
        db_session.add(booking)
        db_session.commit()
        booking_id = booking.id

        response = client.delete(
            f"/api/v1/bookings/{booking_id}", headers=auth_headers
        )
        assert response.status_code == 204

        db_session.expire_all()
        updated_booking = db_session.query(Booking).filter(Booking.id == booking_id).first()
        assert updated_booking.status == BookingStatus.CANCELLED

    def test_create_booking_with_device(self, client, test_user, test_room_id, test_device_id, auth_headers):
        future_start = datetime.now() + timedelta(hours=2)
        future_end = future_start + timedelta(hours=1)

        response = client.post(
            "/api/v1/bookings",
            json={
                "title": "带设备的会议",
                "room_id": test_room_id,
                "start_time": future_start.isoformat(),
                "end_time": future_end.isoformat(),
                "attendee_count": 5,
                "device_ids": [test_device_id],
            },
            headers=auth_headers,
        )
        assert response.status_code == 201
        assert response.json()["success"] is True

    def test_create_booking_exceeds_capacity(self, client, test_room_id, auth_headers, db_session):
        from app.models.models import Room
        test_room = db_session.query(Room).filter(Room.id == test_room_id).first()
        future_start = datetime.now() + timedelta(hours=2)
        future_end = future_start + timedelta(hours=1)

        response = client.post(
            "/api/v1/bookings",
            json={
                "title": "人数超标会议",
                "room_id": test_room_id,
                "start_time": future_start.isoformat(),
                "end_time": future_end.isoformat(),
                "attendee_count": test_room.capacity + 5,
            },
            headers=auth_headers,
        )
        assert response.status_code == 400

    def test_create_booking_past_time(self, client, test_room_id, auth_headers):
        past_start = datetime.now() - timedelta(hours=2)
        past_end = past_start + timedelta(hours=1)

        response = client.post(
            "/api/v1/bookings",
            json={
                "title": "过去的会议",
                "room_id": test_room_id,
                "start_time": past_start.isoformat(),
                "end_time": past_end.isoformat(),
                "attendee_count": 3,
            },
            headers=auth_headers,
        )
        assert response.status_code == 400


class TestCalendar:
    def test_get_calendar_view(self, client, test_room_id, test_user_id, auth_headers, db_session):
        start_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        end_date = start_date + timedelta(days=7)

        future_start = start_date + timedelta(days=1, hours=10)
        future_end = future_start + timedelta(hours=1)

        booking = Booking(
            room_id=test_room_id,
            user_id=test_user_id,
            title="日历测试会议",
            start_time=future_start,
            end_time=future_end,
            status=BookingStatus.CONFIRMED,
            recurrence_type=RecurrenceType.NONE,
        )
        db_session.add(booking)
        db_session.commit()

        response = client.get(
            "/api/v1/calendar/view",
            params={
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "room_ids": [test_room_id],
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert "calendar" in response.json()
        assert len(response.json()["rooms"]) == 1

    def test_get_daily_view(self, client, test_room_id, auth_headers):
        today = datetime.now()

        response = client.get(
            f"/api/v1/calendar/room/{test_room_id}/daily",
            params={"date": today.isoformat()},
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert "time_slots" in response.json()
        assert len(response.json()["time_slots"]) == 48

    def test_get_available_slots(self, client, test_room_id, auth_headers):
        start_date = datetime.now() + timedelta(hours=1)
        end_date = start_date + timedelta(hours=5)

        response = client.get(
            "/api/v1/calendar/available-slots",
            params={
                "room_id": test_room_id,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "duration_minutes": 60,
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert "available_slots" in response.json()

    def test_get_week_view(self, client, test_room_id, auth_headers):
        response = client.get(
            "/api/v1/calendar/week",
            params={"room_ids": [test_room_id]},
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert len(response.json()["calendar"]) == 7

    def test_get_month_view(self, client, test_room_id, auth_headers):
        now = datetime.now()
        response = client.get(
            "/api/v1/calendar/month",
            params={"year": now.year, "month": now.month, "room_ids": [test_room_id]},
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert "calendar" in response.json()


class TestBatchCancel:
    def test_batch_cancel_by_ids(self, client, test_user, test_room, auth_headers, db_session):
        booking_ids = []
        for i in range(3):
            future_start = datetime.now() + timedelta(days=i + 1, hours=10)
            future_end = future_start + timedelta(hours=1)

            booking = Booking(
                room_id=test_room.id,
                user_id=test_user.id,
                title=f"批量测试会议{i}",
                start_time=future_start,
                end_time=future_end,
                status=BookingStatus.CONFIRMED,
                recurrence_type=RecurrenceType.NONE,
            )
            db_session.add(booking)
            db_session.flush()
            booking_ids.append(booking.id)
        db_session.commit()

        response = client.post(
            "/api/v1/batch/cancel",
            json={"booking_ids": booking_ids},
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["cancelled_count"] == 3
        assert len(response.json()["cancelled_ids"]) == 3

    def test_batch_cancel_by_series(self, client, test_user, test_room, auth_headers, db_session):
        series_id = "test-series-123"
        for i in range(3):
            future_start = datetime.now() + timedelta(days=i + 1, hours=10)
            future_end = future_start + timedelta(hours=1)

            booking = Booking(
                room_id=test_room.id,
                user_id=test_user.id,
                title=f"系列会议{i}",
                start_time=future_start,
                end_time=future_end,
                status=BookingStatus.CONFIRMED,
                recurrence_type=RecurrenceType.WEEKLY,
                series_id=series_id,
            )
            db_session.add(booking)
        db_session.commit()

        response = client.post(
            "/api/v1/batch/cancel",
            json={"series_id": series_id},
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["cancelled_count"] == 3

    def test_batch_cancel_by_date_range(self, client, test_user, test_room, auth_headers, db_session):
        start_range = datetime.now() + timedelta(days=2)
        end_range = datetime.now() + timedelta(days=5)

        for i in range(5):
            future_start = datetime.now() + timedelta(days=i + 1, hours=10)
            future_end = future_start + timedelta(hours=1)

            booking = Booking(
                room_id=test_room.id,
                user_id=test_user.id,
                title=f"日期范围测试{i}",
                start_time=future_start,
                end_time=future_end,
                status=BookingStatus.CONFIRMED,
                recurrence_type=RecurrenceType.NONE,
            )
            db_session.add(booking)
        db_session.commit()

        response = client.post(
            "/api/v1/batch/cancel",
            json={
                "start_date": start_range.isoformat(),
                "end_date": end_range.isoformat(),
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["cancelled_count"] == 3

    def test_batch_cancel_no_conditions(self, client, auth_headers):
        response = client.post(
            "/api/v1/batch/cancel",
            json={},
            headers=auth_headers,
        )
        assert response.status_code == 400

    def test_cancel_user_bookings(self, client, test_user, test_room, auth_headers, db_session):
        for i in range(2):
            future_start = datetime.now() + timedelta(days=i + 1, hours=10)
            future_end = future_start + timedelta(hours=1)

            booking = Booking(
                room_id=test_room.id,
                user_id=test_user.id,
                title=f"用户预订{i}",
                start_time=future_start,
                end_time=future_end,
                status=BookingStatus.CONFIRMED,
                recurrence_type=RecurrenceType.NONE,
            )
            db_session.add(booking)
        db_session.commit()

        response = client.delete(
            f"/api/v1/batch/cancel/user/{test_user.id}",
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["cancelled_count"] == 2

    def test_cancel_room_bookings(self, client, test_admin, test_room, admin_headers, db_session):
        for i in range(2):
            future_start = datetime.now() + timedelta(days=i + 1, hours=10)
            future_end = future_start + timedelta(hours=1)

            booking = Booking(
                room_id=test_room.id,
                user_id=test_admin.id,
                title=f"会议室预订{i}",
                start_time=future_start,
                end_time=future_end,
                status=BookingStatus.CONFIRMED,
                recurrence_type=RecurrenceType.NONE,
            )
            db_session.add(booking)
        db_session.commit()

        response = client.delete(
            f"/api/v1/batch/cancel/room/{test_room.id}",
            headers=admin_headers,
        )
        assert response.status_code == 200
        assert response.json()["cancelled_count"] == 2

    def test_cancel_room_bookings_unauthorized(self, client, test_room_id, auth_headers):
        response = client.delete(
            f"/api/v1/batch/cancel/room/{test_room_id}",
            headers=auth_headers,
        )
        assert response.status_code == 403


class TestPermission:
    def test_room_requires_approval(self, client, test_user, db_session, auth_headers):
        restricted_room = Room(
            name="需审批会议室",
            location="4楼",
            capacity=6,
            is_active=True,
            requires_approval=True,
            min_booking_duration=30,
            max_booking_duration=240,
        )
        db_session.add(restricted_room)
        db_session.commit()

        future_start = datetime.now() + timedelta(hours=2)
        future_end = future_start + timedelta(hours=1)

        response = client.post(
            "/api/v1/bookings",
            json={
                "title": "需审批会议",
                "room_id": restricted_room.id,
                "start_time": future_start.isoformat(),
                "end_time": future_end.isoformat(),
                "attendee_count": 3,
            },
            headers=auth_headers,
        )
        assert response.status_code == 403

    def test_room_with_permission(self, client, test_user, db_session, auth_headers):
        from app.models.models import RoomPermission

        restricted_room = Room(
            name="权限会议室",
            location="5楼",
            capacity=6,
            is_active=True,
            requires_approval=True,
            min_booking_duration=30,
            max_booking_duration=240,
        )
        db_session.add(restricted_room)
        db_session.flush()

        permission = RoomPermission(
            room_id=restricted_room.id,
            user_id=test_user.id,
            permission_level=PermissionLevel.BOOK,
        )
        db_session.add(permission)
        db_session.commit()

        future_start = datetime.now() + timedelta(hours=2)
        future_end = future_start + timedelta(hours=1)

        response = client.post(
            "/api/v1/bookings",
            json={
                "title": "有权限的会议",
                "room_id": restricted_room.id,
                "start_time": future_start.isoformat(),
                "end_time": future_end.isoformat(),
                "attendee_count": 3,
            },
            headers=auth_headers,
        )
        assert response.status_code == 201
        assert response.json()["success"] is True


class TestBookingSkips:
    def test_skip_single_booking(self, client, test_user_id, test_room_id, auth_headers, db_session):
        future_start = datetime.now() + timedelta(hours=2)
        future_end = future_start + timedelta(hours=1)

        booking = Booking(
            room_id=test_room_id,
            user_id=test_user_id,
            title="待跳过会议",
            start_time=future_start,
            end_time=future_end,
            status=BookingStatus.CONFIRMED,
            recurrence_type=RecurrenceType.NONE,
        )
        db_session.add(booking)
        db_session.commit()
        booking_id = booking.id

        response = client.post(
            "/api/v1/bookings/skip",
            json={
                "booking_id": booking_id,
                "skip_date": future_start.isoformat(),
                "reason": "测试跳过",
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["success"] is True

        db_session.expire_all()
        updated = db_session.query(Booking).filter(Booking.id == booking_id).first()
        assert updated.status == BookingStatus.SKIPPED

    def test_skip_booking_in_series(self, client, test_user_id, test_room_id, auth_headers, db_session):
        from app.schemas.schemas import BookingCreate, RecurrenceConfig
        from app.services.booking_service import create_recurring_bookings

        future_start = datetime.now() + timedelta(days=1, hours=10)
        future_end = future_start + timedelta(hours=1)

        booking_data = BookingCreate(
            title="循环会议",
            room_id=test_room_id,
            start_time=future_start,
            end_time=future_end,
            attendee_count=3,
            recurrence=RecurrenceConfig(
                recurrence_type=RecurrenceType.DAILY,
                recurrence_end_date=future_start + timedelta(days=5),
            ),
        )

        created_bookings, errors = create_recurring_bookings(db_session, booking_data, test_user_id)
        assert len(created_bookings) > 0
        series_id = created_bookings[0].series_id

        skip_date = future_start + timedelta(days=2)
        response = client.post(
            "/api/v1/bookings/skip",
            json={
                "series_id": series_id,
                "skip_date": skip_date.isoformat(),
                "reason": "跳过第三次",
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["success"] is True

        response = client.get(
            f"/api/v1/bookings/skips/series/{series_id}",
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert len(response.json()) >= 1


class TestSuggestionScoring:
    def test_alternatives_have_scores(self, client, test_room_id, test_room_b_id, auth_headers, db_session):
        future_start = datetime.now() + timedelta(hours=2)
        future_end = future_start + timedelta(hours=1)

        existing = Booking(
            room_id=test_room_id,
            user_id=1,
            title="冲突会议",
            start_time=future_start,
            end_time=future_end,
            status=BookingStatus.CONFIRMED,
        )
        db_session.add(existing)
        db_session.commit()

        response = client.get(
            "/api/v1/bookings/check-conflict",
            params={
                "room_id": test_room_id,
                "start_time": future_start.isoformat(),
                "end_time": future_end.isoformat(),
                "attendee_count": 5,
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["has_conflict"] is True

        alternatives = response.json()["alternatives"]
        assert len(alternatives) > 0

        first_alt = alternatives[0]
        assert "score" in first_alt
        assert "score_level" in first_alt
        assert "score_reasons" in first_alt
        assert isinstance(first_alt["score"], float)
        assert first_alt["score"] >= 0
        assert first_alt["score"] <= 1


class TestCalendarTimezone:
    def test_calendar_view_with_timezone(self, client, test_room_id, auth_headers):
        start_date = datetime.now()
        end_date = start_date + timedelta(days=3)

        response = client.get(
            "/api/v1/calendar/view",
            params={
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "room_ids": [test_room_id],
                "timezone": "Asia/Tokyo",
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["timezone"] == "Asia/Tokyo"

    def test_daily_view_with_timezone(self, client, test_room_id, auth_headers):
        today = datetime.now()

        response = client.get(
            f"/api/v1/calendar/room/{test_room_id}/daily",
            params={
                "date": today.isoformat(),
                "timezone": "America/New_York",
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["timezone"] == "America/New_York"


class TestAvailableSlotsWithDevices:
    def test_available_slots_with_device_filter(
        self, client, test_room_id, test_device_id, auth_headers, db_session
    ):
        from app.models.models import RoomDevice

        rd = RoomDevice(room_id=test_room_id, device_id=test_device_id, is_permanent=True)
        db_session.add(rd)
        db_session.commit()

        start_date = datetime.now() + timedelta(hours=1)
        end_date = start_date + timedelta(hours=5)

        response = client.get(
            "/api/v1/calendar/available-slots",
            params={
                "room_id": test_room_id,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "duration_minutes": 60,
                "device_ids": [test_device_id],
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert "available_slots" in response.json()
        assert "total_count" in response.json()

        slots = response.json()["available_slots"]
        if slots:
            assert slots[0]["has_all_devices"] is True
            assert test_device_id in slots[0]["available_device_ids"]

    def test_available_slots_with_min_capacity(
        self, client, test_room_id, test_room_b_id, auth_headers
    ):
        start_date = datetime.now() + timedelta(hours=1)
        end_date = start_date + timedelta(hours=5)

        response = client.get(
            "/api/v1/calendar/available-slots",
            params={
                "room_ids": [test_room_id, test_room_b_id],
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "duration_minutes": 60,
                "min_capacity": 5,
            },
            headers=auth_headers,
        )
        assert response.status_code == 200


class TestCancellationApproval:
    def test_create_cancellation_request(self, client, test_user_id, test_room_id, auth_headers, db_session):
        future_start = datetime.now() + timedelta(hours=2)
        future_end = future_start + timedelta(hours=1)

        booking = Booking(
            room_id=test_room_id,
            user_id=test_user_id,
            title="待审批取消会议",
            start_time=future_start,
            end_time=future_end,
            status=BookingStatus.CONFIRMED,
        )
        db_session.add(booking)
        db_session.commit()
        booking_id = booking.id

        response = client.post(
            "/api/v1/cancellations",
            json={
                "booking_ids": [booking_id],
                "reason": "需要取消",
                "cancellation_type": "ids",
            },
            headers=auth_headers,
        )
        assert response.status_code == 201
        assert response.json()["status"] == "pending"

    def test_get_my_cancellation_requests(self, client, auth_headers):
        response = client.get(
            "/api/v1/cancellations/my",
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_approve_cancellation_request(
        self, client, test_user_id, test_room_id, admin_headers, db_session
    ):
        future_start = datetime.now() + timedelta(hours=2)
        future_end = future_start + timedelta(hours=1)

        booking = Booking(
            room_id=test_room_id,
            user_id=test_user_id,
            title="待批准取消的会议",
            start_time=future_start,
            end_time=future_end,
            status=BookingStatus.CONFIRMED,
        )
        db_session.add(booking)
        db_session.commit()
        booking_id = booking.id

        from app.models.models import CancellationRequest, CancellationRequestStatus

        request = CancellationRequest(
            requester_id=test_user_id,
            booking_ids=[booking_id],
            status=CancellationRequestStatus.PENDING,
            cancellation_type="ids",
        )
        db_session.add(request)
        db_session.commit()
        request_id = request.id

        response = client.post(
            f"/api/v1/cancellations/{request_id}/approve",
            params={"approval_reason": "批准取消"},
            headers=admin_headers,
        )
        assert response.status_code == 200
        assert response.json()["success"] is True

        db_session.expire_all()
        updated = db_session.query(Booking).filter(Booking.id == booking_id).first()
        assert updated.status == BookingStatus.CANCELLED


class TestCancellationRollback:
    def test_rollback_cancellation(
        self, client, test_user_id, test_room_id, admin_headers, db_session
    ):
        from app.models.models import (
            CancellationRequest,
            CancellationRequestStatus,
            CancellationAuditLog,
        )

        future_start = datetime.now() + timedelta(hours=2)
        future_end = future_start + timedelta(hours=1)

        booking = Booking(
            room_id=test_room_id,
            user_id=test_user_id,
            title="待回滚取消的会议",
            start_time=future_start,
            end_time=future_end,
            status=BookingStatus.CANCELLED,
        )
        db_session.add(booking)
        db_session.flush()
        booking_id = booking.id

        request = CancellationRequest(
            requester_id=test_user_id,
            booking_ids=[booking_id],
            status=CancellationRequestStatus.APPROVED,
            cancellation_type="ids",
        )
        db_session.add(request)
        db_session.flush()
        request_id = request.id

        audit_log = CancellationAuditLog(
            request_id=request_id,
            booking_id=booking_id,
            original_status=BookingStatus.CONFIRMED,
            new_status=BookingStatus.CANCELLED,
            action_type="cancellation",
        )
        db_session.add(audit_log)
        db_session.commit()

        response = client.post(
            "/api/v1/cancellations/rollback",
            json={"request_id": request_id, "reason": "回滚测试"},
            headers=admin_headers,
        )
        assert response.status_code == 200
        assert response.json()["success"] is True
        assert response.json()["restored_count"] == 1

        db_session.expire_all()
        restored = db_session.query(Booking).filter(Booking.id == booking_id).first()
        assert restored.status == BookingStatus.CONFIRMED


class TestDelegation:
    def test_create_delegation(self, client, test_user_id, test_room_id, auth_headers, db_session):
        from app.models.models import User

        delegate_user = User(
            username="delegateuser",
            email="delegate@example.com",
            full_name="Delegate User",
            hashed_password=get_password_hash("delegate123"),
            permission_level=PermissionLevel.BOOK,
        )
        db_session.add(delegate_user)
        db_session.commit()
        delegate_id = delegate_user.id

        response = client.post(
            "/api/v1/delegations",
            json={
                "delegate_id": delegate_id,
                "room_id": test_room_id,
                "reason": "出差期间代订",
            },
            headers=auth_headers,
        )
        assert response.status_code == 201
        assert response.json()["delegator_id"] == test_user_id
        assert response.json()["delegate_id"] == delegate_id

    def test_get_my_delegations(self, client, auth_headers):
        response = client.get(
            "/api/v1/delegations/from-me",
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_get_delegations_to_me(self, client, auth_headers):
        response = client.get(
            "/api/v1/delegations/to-me",
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_booking_with_delegation(
        self, client, test_user_id, test_room_id, auth_headers, db_session
    ):
        from app.models.models import User, BookingDelegation
        from app.dependencies import create_access_token

        delegate_user = User(
            username="delegateuser2",
            email="delegate2@example.com",
            full_name="Delegate User 2",
            hashed_password=get_password_hash("delegate123"),
            permission_level=PermissionLevel.BOOK,
        )
        db_session.add(delegate_user)
        db_session.flush()
        delegate_id = delegate_user.id

        delegation = BookingDelegation(
            delegator_id=test_user_id,
            delegate_id=delegate_id,
            room_id=test_room_id,
            is_active=True,
        )
        db_session.add(delegation)
        db_session.commit()

        token = create_access_token(data={"sub": delegate_user.username})
        delegate_headers = {"Authorization": f"Bearer {token}"}

        future_start = datetime.now() + timedelta(hours=2)
        future_end = future_start + timedelta(hours=1)

        response = client.post(
            "/api/v1/bookings",
            json={
                "title": "代订的会议",
                "room_id": test_room_id,
                "start_time": future_start.isoformat(),
                "end_time": future_end.isoformat(),
                "attendee_count": 3,
                "delegate_user_id": test_user_id,
            },
            headers=delegate_headers,
        )
        assert response.status_code == 201
        assert response.json()["success"] is True

        booking = response.json()["bookings"][0]
        assert booking["user_id"] == test_user_id
        assert booking["delegation_id"] is not None


class TestCoverage:
    def test_root_endpoint_features(self, client):
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert "features" in data
        assert len(data["features"]) > 5
        assert data["version"] == "2.1.0"

    def test_health_check_v2(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["version"] == "2.1.0"


class TestSuggestionConfig:
    def test_get_suggestion_config(self, client, auth_headers):
        response = client.get(
            "/api/v1/bookings/suggestion-config",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert "weights" in data
        assert "thresholds" in data
        assert "time" in data["weights"]
        assert "room" in data["weights"]
        assert "device" in data["weights"]
        assert "excellent" in data["thresholds"]
        assert "good" in data["thresholds"]
        assert "fair" in data["thresholds"]

    def test_score_levels_use_config(self, client, test_room_id, test_room_b_id, auth_headers, db_session):
        from app.config import settings

        future_start = datetime.now() + timedelta(hours=2)
        future_end = future_start + timedelta(hours=1)

        existing = Booking(
            room_id=test_room_id,
            user_id=1,
            title="冲突会议",
            start_time=future_start,
            end_time=future_end,
            status=BookingStatus.CONFIRMED,
        )
        db_session.add(existing)
        db_session.commit()

        response = client.get(
            "/api/v1/bookings/check-conflict",
            params={
                "room_id": test_room_id,
                "start_time": future_start.isoformat(),
                "end_time": future_end.isoformat(),
                "attendee_count": 5,
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        alternatives = response.json()["alternatives"]
        assert len(alternatives) > 0

        for alt in alternatives:
            score = alt["score"]
            level = alt["score_level"]
            if score >= settings.SUGGESTION_SCORE_LEVEL_EXCELLENT:
                assert level == "excellent"
            elif score >= settings.SUGGESTION_SCORE_LEVEL_GOOD:
                assert level == "good"
            elif score >= settings.SUGGESTION_SCORE_LEVEL_FAIR:
                assert level == "fair"
            else:
                assert level == "poor"


class TestDelegationRevoke:
    def test_revoke_delegation(self, client, test_user_id, test_room_id, auth_headers, db_session):
        from app.models.models import User, BookingDelegation

        delegate_user = User(
            username="revoketestuser",
            email="revoke@example.com",
            full_name="Revoke Test User",
            hashed_password=get_password_hash("revoke123"),
            permission_level=PermissionLevel.BOOK,
        )
        db_session.add(delegate_user)
        db_session.flush()
        delegate_id = delegate_user.id

        delegation = BookingDelegation(
            delegator_id=test_user_id,
            delegate_id=delegate_id,
            room_id=test_room_id,
            is_active=True,
        )
        db_session.add(delegation)
        db_session.commit()
        delegation_id = delegation.id

        response = client.post(
            f"/api/v1/delegations/{delegation_id}/revoke",
            json={"reason": "不需要代订了"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["is_active"] is False
        assert response.json()["revoked_at"] is not None
        assert response.json()["revoked_by"] == test_user_id
        assert response.json()["revocation_reason"] == "不需要代订了"

    def test_revoke_inactive_delegation_fails(self, client, test_user_id, test_room_id, auth_headers, db_session):
        from app.models.models import User, BookingDelegation

        delegate_user = User(
            username="revokefailuser",
            email="revokefail@example.com",
            full_name="Revoke Fail User",
            hashed_password=get_password_hash("revoke123"),
            permission_level=PermissionLevel.BOOK,
        )
        db_session.add(delegate_user)
        db_session.flush()
        delegate_id = delegate_user.id

        delegation = BookingDelegation(
            delegator_id=test_user_id,
            delegate_id=delegate_id,
            room_id=test_room_id,
            is_active=False,
        )
        db_session.add(delegation)
        db_session.commit()
        delegation_id = delegation.id

        response = client.post(
            f"/api/v1/delegations/{delegation_id}/revoke",
            json={},
            headers=auth_headers,
        )
        assert response.status_code == 400


class TestCancellationTimeout:
    def test_process_timeout_requests_reject(
        self, client, test_user_id, test_room_id, admin_headers, db_session
    ):
        from app.models.models import CancellationRequest, CancellationRequestStatus

        future_start = datetime.now() + timedelta(hours=2)
        future_end = future_start + timedelta(hours=1)

        booking = Booking(
            room_id=test_room_id,
            user_id=test_user_id,
            title="超时测试会议",
            start_time=future_start,
            end_time=future_end,
            status=BookingStatus.CONFIRMED,
        )
        db_session.add(booking)
        db_session.flush()
        booking_id = booking.id

        old_created = datetime.utcnow() - timedelta(hours=72)
        request = CancellationRequest(
            requester_id=test_user_id,
            booking_ids=[booking_id],
            status=CancellationRequestStatus.PENDING,
            cancellation_type="ids",
        )
        request.created_at = old_created
        db_session.add(request)
        db_session.commit()
        request_id = request.id

        response = client.post(
            "/api/v1/cancellations/process-timeouts",
            params={"timeout_hours": 48, "action": "reject"},
            headers=admin_headers,
        )
        assert response.status_code == 200
        assert response.json()["processed"] >= 1
        assert response.json()["rejected"] >= 1

        db_session.expire_all()
        updated = db_session.query(CancellationRequest).filter(CancellationRequest.id == request_id).first()
        assert updated.status == CancellationRequestStatus.REJECTED


class TestAuditLogCleanup:
    def test_cleanup_expired_audit_logs(
        self, client, test_user_id, test_room_id, admin_headers, db_session
    ):
        from app.models.models import (
            CancellationRequest,
            CancellationRequestStatus,
            CancellationAuditLog,
        )

        future_start = datetime.now() + timedelta(hours=2)
        future_end = future_start + timedelta(hours=1)

        booking = Booking(
            room_id=test_room_id,
            user_id=test_user_id,
            title="清理测试会议",
            start_time=future_start,
            end_time=future_end,
            status=BookingStatus.CANCELLED,
        )
        db_session.add(booking)
        db_session.flush()
        booking_id = booking.id

        request = CancellationRequest(
            requester_id=test_user_id,
            booking_ids=[booking_id],
            status=CancellationRequestStatus.APPROVED,
            cancellation_type="ids",
        )
        db_session.add(request)
        db_session.flush()
        request_id = request.id

        old_log = CancellationAuditLog(
            request_id=request_id,
            booking_id=booking_id,
            original_status=BookingStatus.CONFIRMED,
            new_status=BookingStatus.CANCELLED,
            action_type="cancellation",
        )
        old_log.created_at = datetime.utcnow() - timedelta(days=100)
        db_session.add(old_log)

        new_log = CancellationAuditLog(
            request_id=request_id,
            booking_id=booking_id,
            original_status=BookingStatus.CONFIRMED,
            new_status=BookingStatus.CANCELLED,
            action_type="cancellation",
        )
        db_session.add(new_log)
        db_session.commit()

        response = client.post(
            "/api/v1/cancellations/cleanup-audit-logs",
            params={"retention_days": 90},
            headers=admin_headers,
        )
        assert response.status_code == 200
        assert response.json()["deleted_count"] >= 1


class TestDSTHandling:
    def test_dst_transition_detection(self):
        from app.routers.calendar import _is_dst_transition_day
        from datetime import datetime as dt

        test_date_nyc_spring = dt(2024, 3, 10)
        result_spring = _is_dst_transition_day(test_date_nyc_spring, "America/New_York")
        assert isinstance(result_spring, dict)
        assert "is_dst_transition" in result_spring

        test_date_nyc_fall = dt(2024, 11, 3)
        result_fall = _is_dst_transition_day(test_date_nyc_fall, "America/New_York")
        assert isinstance(result_fall, dict)


class TestCoverageSLA:
    def test_coverage_sla_config_exists(self):
        from app.config import settings

        assert hasattr(settings, "COVERAGE_SLA_TARGET")
        assert settings.COVERAGE_SLA_TARGET > 0
        assert settings.COVERAGE_SLA_TARGET <= 100

    def test_pytest_ini_exists(self):
        import os

        ini_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "pytest.ini",
        )
        assert os.path.exists(ini_path)


class TestDeviceBonusAutoTuning:
    def test_device_bonus_config_endpoint(self, client, auth_headers):
        response = client.get(
            "/api/v1/advanced/device-bonus/config",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert "enabled" in data
        assert "base_cap" in data
        assert "max_cap" in data
        assert "per_device_weight" in data

    def test_device_bonus_settings_exist(self):
        from app.config import settings

        assert hasattr(settings, "DEVICE_BONUS_CAP_ENABLED")
        assert hasattr(settings, "DEVICE_BONUS_BASE_CAP")
        assert hasattr(settings, "DEVICE_BONUS_CAP_PER_DEVICE")
        assert hasattr(settings, "DEVICE_BONUS_MAX_CAP")
        assert settings.DEVICE_BONUS_MAX_CAP >= settings.DEVICE_BONUS_BASE_CAP


class TestNotifications:
    def test_list_notifications(self, client, auth_headers):
        response = client.get(
            "/api/v1/advanced/notifications",
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_notification_with_dst_type(self, client, test_user_id, auth_headers, db_session):
        from app.models.models import Notification, NotificationType, NotificationStatus

        notification = Notification(
            user_id=test_user_id,
            title="测试通知",
            content="测试内容",
            notification_type=NotificationType.DST_REMINDER,
            status=NotificationStatus.UNREAD,
        )
        db_session.add(notification)
        db_session.commit()
        notification_id = notification.id

        response = client.get(
            "/api/v1/advanced/notifications",
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert len(response.json()) >= 1

    def test_mark_notification_read(self, client, test_user_id, auth_headers, db_session):
        from app.models.models import Notification, NotificationType, NotificationStatus

        notification = Notification(
            user_id=test_user_id,
            title="未读通知",
            content="测试内容",
            notification_type=NotificationType.SYSTEM,
            status=NotificationStatus.UNREAD,
        )
        db_session.add(notification)
        db_session.commit()
        notification_id = notification.id

        response = client.post(
            f"/api/v1/advanced/notifications/{notification_id}/read",
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["success"] is True


class TestDelegationRevokeAudit:
    def test_revoke_creates_audit_log(self, client, test_user_id, test_room_id, auth_headers, db_session):
        from app.models.models import User, BookingDelegation, DelegationAuditLog

        delegate_user = User(
            username="revokeaudittest",
            email="revokeaudit@example.com",
            full_name="Revoke Audit User",
            hashed_password=get_password_hash("test123"),
            permission_level=PermissionLevel.BOOK,
        )
        db_session.add(delegate_user)
        db_session.flush()
        delegate_id = delegate_user.id

        delegation = BookingDelegation(
            delegator_id=test_user_id,
            delegate_id=delegate_id,
            room_id=test_room_id,
            is_active=True,
        )
        db_session.add(delegation)
        db_session.commit()
        delegation_id = delegation.id

        response = client.post(
            f"/api/v1/delegations/{delegation_id}/revoke",
            json={"reason": "审计测试"},
            headers=auth_headers,
        )
        assert response.status_code == 200

        audit_logs = db_session.query(DelegationAuditLog).filter(
            DelegationAuditLog.delegation_id == delegation_id
        ).all()
        assert len(audit_logs) >= 1
        assert audit_logs[0].action_type == "revoke"

    def test_get_delegation_audit_logs(self, client, test_user_id, test_room_id, auth_headers, db_session):
        from app.models.models import User, BookingDelegation

        delegate_user = User(
            username="auditlistuser",
            email="auditlist@example.com",
            full_name="Audit List User",
            hashed_password=get_password_hash("test123"),
            permission_level=PermissionLevel.BOOK,
        )
        db_session.add(delegate_user)
        db_session.flush()
        delegate_id = delegate_user.id

        delegation = BookingDelegation(
            delegator_id=test_user_id,
            delegate_id=delegate_id,
            room_id=test_room_id,
            is_active=True,
        )
        db_session.add(delegation)
        db_session.commit()
        delegation_id = delegation.id

        client.post(
            f"/api/v1/delegations/{delegation_id}/revoke",
            json={},
            headers=auth_headers,
        )

        response = client.get(
            f"/api/v1/delegations/{delegation_id}/audit-logs",
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert isinstance(response.json(), list)
        assert len(response.json()) >= 1


class TestTenantConfig:
    def test_set_and_get_tenant_config(self, client, admin_headers):
        response = client.post(
            "/api/v1/advanced/tenant-config/tenant_001",
            params={"config_key": "test_key", "config_value": "test_value"},
            headers=admin_headers,
        )
        assert response.status_code == 200

        response = client.get(
            "/api/v1/advanced/tenant-config/tenant_001",
            params={"config_key": "test_key"},
            headers=admin_headers,
        )
        assert response.status_code == 200
        assert response.json()["value"] == "test_value"

    def test_tenant_approval_timeout(self, client, admin_headers):
        client.post(
            "/api/v1/advanced/tenant-config/tenant_002",
            params={"config_key": "cancellation_approval_timeout_hours", "config_value": 72},
            headers=admin_headers,
        )

        response = client.get(
            "/api/v1/advanced/tenant-config/tenant_002/approval-timeout",
            headers=admin_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert "timeout_hours" in data
        assert "timeout_action" in data


class TestCalibrationSamples:
    def test_add_calibration_sample(self, client, auth_headers):
        response = client.post(
            "/api/v1/advanced/calibration/samples",
            params={
                "original_score": 0.75,
                "adjusted_score": 0.8,
                "score_level": "good",
                "user_feedback": "helpful",
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["original_score"] == 0.75

    def test_get_calibration_stats(self, client, test_user_id, admin_headers, db_session):
        from app.models.models import ScoreCalibrationSample, SuggestionScoreLevel

        for i in range(5):
            sample = ScoreCalibrationSample(
                original_score=0.6 + i * 0.05,
                score_level=SuggestionScoreLevel.GOOD if i % 2 == 0 else SuggestionScoreLevel.FAIR,
                user_feedback="useful" if i % 2 == 0 else "not_useful",
            )
            db_session.add(sample)
        db_session.commit()

        response = client.get(
            "/api/v1/advanced/calibration/stats",
            headers=admin_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert "total_samples" in data
        assert data["total_samples"] >= 5
        assert "level_distribution" in data
        assert "feedback_distribution" in data


class TestABTestExperiment:
    def test_get_ab_test_variant(self, client, auth_headers):
        response = client.get(
            "/api/v1/advanced/ab-test/variant",
            params={"experiment_name": "suggestion_weights"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert "variant" in data
        assert "weights" in data
        assert "ab_test_enabled" in data

    def test_init_ab_test_experiments(self, client, admin_headers):
        response = client.post(
            "/api/v1/advanced/ab-test/experiments/init",
            headers=admin_headers,
        )
        assert response.status_code == 200
        assert "initialized" in response.json()

    def test_list_ab_test_experiments(self, client, admin_headers):
        response = client.get(
            "/api/v1/advanced/ab-test/experiments",
            headers=admin_headers,
        )
        assert response.status_code == 200
        assert isinstance(response.json(), list)


class TestCancellationSnapshot:
    def test_create_cancellation_snapshot(self, client, test_user_id, test_room_id, admin_headers, db_session):
        future_start = datetime.now() + timedelta(hours=2)
        future_end = future_start + timedelta(hours=1)

        booking = Booking(
            room_id=test_room_id,
            user_id=test_user_id,
            title="快照测试会议",
            start_time=future_start,
            end_time=future_end,
            status=BookingStatus.CONFIRMED,
            attendee_count=5,
        )
        db_session.add(booking)
        db_session.commit()
        booking_id = booking.id

        response = client.post(
            f"/api/v1/advanced/cancellation-snapshots/{booking_id}",
            params={"snapshot_type": "test"},
            headers=admin_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert "booking_snapshot" in data
        assert data["booking_snapshot"]["title"] == "快照测试会议"

    def test_cleanup_expired_snapshots(self, client, test_user_id, test_room_id, admin_headers, db_session):
        from app.models.models import CancellationAuditSnapshot
        from datetime import datetime as dt

        future_start = datetime.now() + timedelta(hours=2)
        future_end = future_start + timedelta(hours=1)

        booking = Booking(
            room_id=test_room_id,
            user_id=test_user_id,
            title="快照清理测试",
            start_time=future_start,
            end_time=future_end,
            status=BookingStatus.CONFIRMED,
        )
        db_session.add(booking)
        db_session.flush()
        booking_id = booking.id

        old_snapshot = CancellationAuditSnapshot(
            snapshot_date=dt.utcnow() - timedelta(days=400),
            booking_id=booking_id,
            booking_snapshot={"title": "old"},
            snapshot_type="cancellation",
        )
        old_snapshot.created_at = dt.utcnow() - timedelta(days=400)
        db_session.add(old_snapshot)
        db_session.commit()

        response = client.post(
            "/api/v1/advanced/cancellation-snapshots/cleanup",
            params={"retention_days": 365},
            headers=admin_headers,
        )
        assert response.status_code == 200
        assert response.json()["deleted_count"] >= 1


class TestCoverageModuleTargets:
    def test_module_coverage_targets(self):
        from app.services.advanced_service import parse_module_coverage_targets

        targets = parse_module_coverage_targets()
        assert isinstance(targets, dict)
        assert len(targets) > 0
        for module, target in targets.items():
            assert isinstance(target, float)
            assert target > 0
            assert target <= 100

    def test_coverage_sla_init(self, client, admin_headers):
        response = client.post(
            "/api/v1/advanced/coverage-sla/init",
            headers=admin_headers,
        )
        assert response.status_code == 200
        assert "initialized" in response.json()

    def test_coverage_sla_configs(self, client, admin_headers):
        response = client.get(
            "/api/v1/advanced/coverage-sla/configs",
            headers=admin_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert "configs" in data
        assert "configured_targets" in data
        assert "global_target" in data
