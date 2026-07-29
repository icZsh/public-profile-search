import pytest

from apps.api.app.core.crypto import (
    UnsafePrototypeUrl,
    canonicalize_github_profile_url,
)


@pytest.mark.parametrize(
    "value",
    [
        "http://github.com/octocat",
        "https://github.com.evil.example/octocat",
        "https://evil.example/github.com/octocat",
        "https://user@github.com/octocat",
        "https://github.com:443/octocat",
        "https://github.com/octocat?tab=repositories",
        "https://github.com/octocat?",
        "https://github.com/octocat#bio",
        "https://github.com/octocat#",
        "https://github.com/octocat/repositories",
        "https://github.com/octocat%2Frepositories",
        "https://github.com\\@evil.example/octocat",
        "https://github.com/.well-known",
        "https://github.com/-octocat",
        "https://github.com/octocat-",
        "https://github.com/octo--cat",
        "https://githüb.com/octocat",
        "https://github.com/\u2603",
        "https://github.com/" + ("a" * 40),
    ],
)
def test_rejects_noncanonical_or_unsafe_github_profile_urls(value: str):
    with pytest.raises(UnsafePrototypeUrl):
        canonicalize_github_profile_url(value)


@pytest.mark.parametrize(
    "value",
    [
        "https://github.com/OctoCat",
        "https://GITHUB.com/octocat/",
        "  https://github.com/octocat  ",
    ],
)
def test_equivalent_github_profile_urls_collapse_to_one_identifier(value: str):
    target = canonicalize_github_profile_url(value)
    assert target.canonical_url == "https://github.com/octocat"
    assert target.handle == "octocat"
    assert target.provider_id == "github_public_profile_v1"
