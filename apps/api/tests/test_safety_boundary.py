import json
from pathlib import Path

import pytest

from apps.api.app.safe_fetch.service import NetworkFetchDisabled, SafeFetchGateway
from workers.providers.registry import FIXTURE_DIRECTORY, PROVIDER_FIXTURES

FORBIDDEN_KEYS = {
    "email",
    "phone",
    "address",
    "birthday",
    "age",
    "location",
    "religion",
    "politics",
    "ethnicity",
    "medical",
    "photo",
}


def walk_keys(value):
    if isinstance(value, dict):
        for key, nested in value.items():
            yield key.casefold()
            yield from walk_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from walk_keys(nested)


def test_fixture_provider_has_no_network_implementation():
    with pytest.raises(NetworkFetchDisabled):
        SafeFetchGateway().fetch("https://example.com")


@pytest.mark.parametrize("filename", PROVIDER_FIXTURES.values())
def test_fixtures_do_not_contain_prohibited_fields(filename: str):
    payload = json.loads((Path(FIXTURE_DIRECTORY) / filename).read_text())
    assert FORBIDDEN_KEYS.isdisjoint(set(walk_keys(payload)))
    serialized = json.dumps(payload).casefold()
    assert "@" not in serialized
    assert "http://" not in serialized
