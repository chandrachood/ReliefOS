import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings


@pytest.fixture
def client(tmp_path):
    settings = Settings(
        app_env="test",
        auth_mode="local",
        storage_backend="memory",
        case_access_secret="test-secret-that-is-not-for-production",
        local_media_path=tmp_path / "media",
    )
    with TestClient(create_app(settings)) as test_client:
        yield test_client


@pytest.fixture
def citizen_headers():
    return {"X-Actor-ID": "citizen-1", "X-Actor-Role": "citizen"}


@pytest.fixture
def coordinator_headers():
    return {"X-Actor-ID": "coordinator-1", "X-Actor-Role": "coordinator"}


@pytest.fixture
def urgent_case_payload():
    return {
        "case_type": "trapped",
        "reporter": {"name": "Test Reporter", "phone": "+91 9000000000"},
        "affected_people_count": 3,
        "description": "Three people are trapped and water is rising.",
        "latitude": 10.7867,
        "longitude": 76.6548,
        "gps_accuracy_meters": 12,
        "danger_indicators": ["rising_water", "people_trapped"],
        "requested_assistance": ["rescue", "boat"],
        "preferred_language": "en-IN",
    }
