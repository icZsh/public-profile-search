import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from cryptography.fernet import Fernet, InvalidToken


class UnsafePrototypeUrl(ValueError):
    pass


class InvalidEncryptedValue(ValueError):
    pass


@dataclass(frozen=True)
class ProfileTarget:
    provider_id: str
    canonical_url: str
    handle: str
    fixture_key: str | None
    canonicalization_version: str = "profile-url-v1"


GITHUB_LOGIN_PATTERN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}\Z")


def _reject_ambiguous_url_syntax(value: str) -> str:
    stripped = value.strip()
    if not stripped or len(stripped) > 300:
        raise UnsafePrototypeUrl("Profile URL length is invalid")
    if not stripped.isascii():
        raise UnsafePrototypeUrl("Only ASCII profile URLs are accepted")
    if any(ord(character) < 32 or ord(character) == 127 for character in stripped):
        raise UnsafePrototypeUrl("Control characters are not accepted")
    if any(character in stripped for character in ("\\", "%", "?", "#")):
        raise UnsafePrototypeUrl("Encoded, ambiguous, query, and fragment syntax is rejected")
    return stripped


def canonicalize_fixture_url(value: str, allowed_urls: set[str]) -> str:
    stripped = _reject_ambiguous_url_syntax(value)
    try:
        parts = urlsplit(stripped)
        port = parts.port
    except ValueError as exc:
        raise UnsafePrototypeUrl("The fixture URL is invalid") from exc
    if parts.scheme != "https" or not parts.hostname:
        raise UnsafePrototypeUrl("Only HTTPS fixture URLs are accepted")
    if parts.username or parts.password or port is not None:
        raise UnsafePrototypeUrl("Credentials and custom ports are not accepted")
    if parts.query or parts.fragment:
        raise UnsafePrototypeUrl("Query strings and fragments are not accepted")
    canonical = urlunsplit(("https", parts.hostname.lower(), parts.path.rstrip("/"), "", ""))
    if canonical not in allowed_urls:
        raise UnsafePrototypeUrl("Unknown fixture URL")
    return canonical


def canonicalize_github_profile_url(value: str) -> ProfileTarget:
    stripped = _reject_ambiguous_url_syntax(value)
    try:
        parts = urlsplit(stripped)
        port = parts.port
    except ValueError as exc:
        raise UnsafePrototypeUrl("The GitHub profile URL is invalid") from exc
    if parts.scheme != "https":
        raise UnsafePrototypeUrl("Only HTTPS GitHub profile URLs are accepted")
    if (
        not parts.hostname
        or parts.hostname.casefold() != "github.com"
        or parts.netloc.casefold() != "github.com"
    ):
        raise UnsafePrototypeUrl("Only the github.com profile host is accepted")
    if parts.username or parts.password or port is not None:
        raise UnsafePrototypeUrl("Credentials and ports are not accepted")
    if parts.query or parts.fragment:
        raise UnsafePrototypeUrl("Query strings and fragments are not accepted")

    path = parts.path
    if path.endswith("/"):
        path = path[:-1]
    if not path.startswith("/") or path.count("/") != 1:
        raise UnsafePrototypeUrl("A direct GitHub profile URL is required")
    login = path[1:]
    if not GITHUB_LOGIN_PATTERN.fullmatch(login):
        raise UnsafePrototypeUrl("The GitHub profile handle is invalid")
    normalized_login = login.casefold()
    return ProfileTarget(
        provider_id="github_public_profile_v1",
        canonical_url=f"https://github.com/{normalized_login}",
        handle=normalized_login,
        fixture_key=None,
    )


def canonicalize_profile_url(
    value: str,
    *,
    fixture_url: str,
    allow_fixture: bool = True,
) -> ProfileTarget:
    if allow_fixture:
        try:
            fixture = canonicalize_fixture_url(value, {fixture_url})
        except UnsafePrototypeUrl:
            pass
        else:
            return ProfileTarget(
                provider_id="fixture_primary_v1",
                canonical_url=fixture,
                handle="alex-chen",
                fixture_key="alex-chen",
            )
    return canonicalize_github_profile_url(value)


def keyed_hmac(value: str, key: str) -> str:
    return hmac.new(key.encode(), value.encode(), hashlib.sha256).hexdigest()


def hmac_matches(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode(), right.encode())


def _secret_value(key: object) -> str:
    get_secret_value = getattr(key, "get_secret_value", None)
    return str(get_secret_value() if get_secret_value else key)


def encrypt_value(value: str, key: object) -> str:
    return Fernet(_secret_value(key).encode()).encrypt(value.encode()).decode()


def decrypt_value(value: str, key: object) -> str:
    try:
        return Fernet(_secret_value(key).encode()).decrypt(value.encode()).decode()
    except (InvalidToken, ValueError, TypeError) as exc:
        raise InvalidEncryptedValue("Encrypted profile value could not be opened") from exc


def stable_payload_hash(value: dict[str, object]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()
