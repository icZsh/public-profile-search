from dataclasses import dataclass

from fastapi import Request
from fastapi.responses import JSONResponse


@dataclass
class ApiError(Exception):
    status_code: int
    error_code: str
    message: str
    headers: dict[str, str] | None = None


async def api_error_handler(_request: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error_code": exc.error_code, "message": exc.message},
        headers=exc.headers,
    )


def not_found() -> ApiError:
    return ApiError(404, "job_not_found", "The job was not found.")
