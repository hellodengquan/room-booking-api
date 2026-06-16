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
