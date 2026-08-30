import pytest
from pydantic import ValidationError

from app.settings import Settings


def test_production_rejects_local_authentication():
    with pytest.raises(ValidationError):
        Settings(
            app_env="production",
            auth_mode="local",
            case_access_secret="real-secret",
        )


def test_production_rejects_development_secret():
    with pytest.raises(ValidationError):
        Settings(
            app_env="production",
            auth_mode="cognito",
            cognito_user_pool_id="pool",
            cognito_app_client_id="client",
        )


def test_production_rejects_short_secret():
    with pytest.raises(ValidationError):
        Settings(
            app_env="production",
            auth_mode="cognito",
            case_access_secret="short-secret",
            cognito_user_pool_id="pool",
            cognito_app_client_id="client",
        )


def test_ai_requires_bedrock_model_id():
    with pytest.raises(ValidationError):
        Settings(ai_triage_enabled=True)


def test_responses_include_security_headers(client):
    response = client.get("/health/live")

    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
