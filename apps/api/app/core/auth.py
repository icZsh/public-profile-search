from dataclasses import dataclass
from uuid import UUID

from fastapi import Header, Request

from apps.api.app.core.errors import ApiError


@dataclass(frozen=True)
class AuthContext:
    user_id: str


def require_prototype_auth(
    request: Request,
    x_prototype_token: str | None = Header(default=None),
    x_prototype_user: str | None = Header(default=None),
) -> AuthContext:
    settings = request.app.state.settings
    if not x_prototype_token or not hmac_compare(x_prototype_token, settings.prototype_api_token):
        raise ApiError(401, "authentication_required", "Authentication is required.")
    try:
        user_id = str(UUID(x_prototype_user or ""))
    except ValueError as exc:
        raise ApiError(401, "authentication_required", "Authentication is required.") from exc
    return AuthContext(user_id=user_id)


def require_prototype_admin(
    request: Request,
    x_prototype_admin_token: str | None = Header(default=None),
) -> None:
    if not x_prototype_admin_token or not hmac_compare(
        x_prototype_admin_token, request.app.state.settings.prototype_admin_token
    ):
        raise ApiError(401, "authentication_required", "Authentication is required.")


def hmac_compare(left: str, right: str) -> bool:
    import hmac

    return hmac.compare_digest(left.encode(), right.encode())
