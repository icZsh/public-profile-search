from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from apps.api.app.core.clock import FixedClock
from apps.api.app.core.config import Settings
from apps.api.app.main import create_app


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(datetime(2026, 7, 23, 12, 0, tzinfo=UTC))


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'prototype-test.db'}",
        prototype_hmac_key="test-hmac-key-that-is-definitely-long-enough",
        prototype_api_token="test-token",
        prototype_admin_token="test-admin-token",
        professional_search_enabled=False,
    )


@pytest.fixture
def app(settings, clock):
    return create_app(settings=settings, clock=clock)


@pytest.fixture
def client(app):
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def auth_headers(settings) -> dict[str, str]:
    return {
        "X-Prototype-Token": settings.prototype_api_token,
        "X-Prototype-User": str(settings.prototype_user_id),
    }


@pytest.fixture
def create_payload(settings) -> dict[str, str]:
    return {
        "profile_url": settings.fixture_url,
        "purpose": "self_audit",
        "target_relationship": "self",
        "eligibility_reference_id": str(settings.fixture_eligibility_reference_id),
        "attestation_policy_version": settings.policy_version,
        "locale": "en",
    }
