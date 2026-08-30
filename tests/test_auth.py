from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings


def test_unknown_local_role_is_rejected(client):
    response = client.get(
        "/v1/admin/cases",
        headers={"X-Actor-ID": "test", "X-Actor-Role": "invented-role"},
    )

    assert response.status_code == 400


def test_multiple_local_roles_are_supported(client):
    response = client.get(
        "/v1/admin/cases",
        headers={"X-Actor-ID": "test", "X-Actor-Role": "coordinator,responder"},
    )

    assert response.status_code == 200


def test_cognito_mode_allows_anonymous_public_reporting():
    settings = Settings(
        app_env="test",
        auth_mode="cognito",
        storage_backend="memory",
        case_access_secret="test-secret",
        cognito_user_pool_id="test-pool",
        cognito_app_client_id="test-client",
    )
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/v1/cases",
            headers={"X-Actor-ID": "anonymous-device", "Idempotency-Key": "anonymous-report-1"},
            json={
                "case_type": "stranded",
                "description": "Family isolated by floodwater",
                "location_description": "Village school",
            },
        )

    assert response.status_code == 201


def test_non_bearer_authorization_is_rejected():
    settings = Settings(
        app_env="test",
        auth_mode="cognito",
        storage_backend="memory",
        case_access_secret="test-secret",
        cognito_user_pool_id="test-pool",
        cognito_app_client_id="test-client",
    )
    with TestClient(create_app(settings)) as client:
        response = client.get(
            "/v1/admin/cases",
            headers={"Authorization": "Basic not-allowed"},
        )

    assert response.status_code == 401
