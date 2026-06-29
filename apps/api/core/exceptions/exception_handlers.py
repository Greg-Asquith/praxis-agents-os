# apps/api/core/exceptions/exception_handlers.py

"""
Exception handler registration for custom application exceptions.

Maps custom exceptions to RFC 7807 problem+json responses.
"""

import logging
from collections.abc import Mapping
from http import HTTPStatus
from typing import Any, Protocol

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import NoResultFound
from starlette.exceptions import HTTPException as StarletteHTTPException

from core.exceptions.auth import AuthenticationError, AuthorizationError
from core.exceptions.database import DatabaseError
from core.exceptions.general import (
    AppValidationError,
    ConflictError,
    NotFoundError,
    ProblemDetailsError,
    RateLimitError,
    RequestBodyTooLargeError,
)
from core.exceptions.integration import IntegrationError
from core.exceptions.oauth import OAuthError

logger = logging.getLogger("core.exception_handlers")

ProblemDetails = dict[str, Any]
ResponseHeaders = dict[str, str]


class SupportsProblemDetails(Protocol):
    def to_problem_details(self) -> ProblemDetails: ...


APP_EXCEPTION_TYPES: tuple[type[Exception], ...] = (
    AppValidationError,
    NotFoundError,
    ConflictError,
    RequestBodyTooLargeError,
    ProblemDetailsError,
    RateLimitError,
    AuthenticationError,
    AuthorizationError,
    DatabaseError,
    IntegrationError,
    OAuthError,
)


def _status_code(value: Any, default: int = 500) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _response_headers(headers: Any) -> ResponseHeaders | None:
    if not isinstance(headers, Mapping):
        return None

    return {str(key): str(value) for key, value in headers.items() if value is not None}


def _log_level_for_status(status_code: int) -> int:
    if status_code >= 500:
        return logging.ERROR
    if status_code in {401, 403, 429}:
        return logging.WARNING
    return logging.INFO


def _problem_response(
    problem: Mapping[str, Any],
    headers: Mapping[str, Any] | None = None,
) -> JSONResponse:
    content = dict(problem)
    problem_headers = content.pop("headers", None)
    response_headers = _response_headers(problem_headers)
    explicit_headers = _response_headers(headers)

    if explicit_headers:
        response_headers = {**(response_headers or {}), **explicit_headers}

    return JSONResponse(
        status_code=_status_code(content.get("status")),
        content=content,
        media_type="application/problem+json",
        headers=response_headers,
    )


def _validation_error_detail(
    errors: list[ProblemDetails],
    password_message: str | None,
) -> str:
    if password_message:
        return password_message

    summary = "; ".join(
        f"{'.'.join(map(str, error['loc'] or []))}: {error['msg']}"
        if isinstance(error.get("loc"), list)
        else error.get("msg", "Validation error")
        for error in errors[:2]
    )
    return summary or "Request body or parameters failed validation"


async def app_exception_handler(
    request: Request,
    exc: SupportsProblemDetails,
) -> JSONResponse:
    problem = exc.to_problem_details()
    status_code = _status_code(problem.get("status"))
    logger.log(
        _log_level_for_status(status_code),
        "Handled app exception",
        extra={
            "path": str(request.url.path),
            "status_code": status_code,
            "exc_type": exc.__class__.__name__,
        },
    )
    return _problem_response(problem, headers=getattr(exc, "headers", None))


def register_exception_handlers(app: FastAPI) -> None:
    for exc_type in APP_EXCEPTION_TYPES:
        app.add_exception_handler(exc_type, app_exception_handler)

    async def sqlalchemy_no_result_handler(
        request: Request,
        exc: NoResultFound,
    ) -> JSONResponse:
        logger.info(
            "Handled SQLAlchemy NoResultFound",
            extra={
                "path": str(request.url.path),
                "exc_type": exc.__class__.__name__,
            },
        )
        return _problem_response(
            {
                "type": "https://httpstatuses.com/404",
                "title": "Resource Not Found",
                "status": 404,
                "detail": "Resource not found",
            }
        )

    app.add_exception_handler(NoResultFound, sqlalchemy_no_result_handler)

    async def request_validation_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        raw_errors = exc.errors()
        safe_errors: list[ProblemDetails] = []
        first_password_msg: str | None = None

        for err in raw_errors:
            loc = err.get("loc")
            msg = err.get("msg")
            typ = err.get("type")

            if (
                isinstance(loc, (list, tuple))
                and any("password" in str(part).lower() for part in loc)
                and isinstance(msg, str)
            ):
                first_password_msg = first_password_msg or msg

            safe_errors.append(
                {
                    "loc": list(loc) if isinstance(loc, (list, tuple)) else loc,
                    "msg": str(msg) if msg is not None else "Validation error",
                    "type": str(typ) if typ is not None else None,
                }
            )

        problem = {
            "type": "https://httpstatuses.com/422",
            "title": "Request Validation Error",
            "status": 422,
            "detail": _validation_error_detail(safe_errors, first_password_msg),
            "errors": safe_errors,
        }
        logger.info(
            "Handled RequestValidationError",
            extra={
                "path": str(request.url.path),
                "num_errors": len(problem["errors"]),
            },
        )
        return _problem_response(problem)

    app.add_exception_handler(RequestValidationError, request_validation_handler)

    async def http_exception_handler(
        request: Request,
        exc: StarletteHTTPException,
    ) -> JSONResponse:
        status = _status_code(getattr(exc, "status_code", 500))

        if isinstance(exc.detail, dict):
            problem = dict(exc.detail)
            problem.setdefault("status", status)
            problem.setdefault("type", f"https://httpstatuses.com/{status}")
            try:
                problem.setdefault("title", HTTPStatus(status).phrase)
            except ValueError:
                problem.setdefault("title", "HTTP Error")
        else:
            try:
                title = HTTPStatus(status).phrase
            except ValueError:
                title = "HTTP Error"
            detail = exc.detail if isinstance(exc.detail, str) else "HTTP error"
            problem = {
                "type": f"https://httpstatuses.com/{status}",
                "title": title,
                "status": status,
                "detail": detail,
            }

        logger.warning(
            "Handled HTTPException",
            extra={
                "path": str(request.url.path),
                "status_code": status,
                "detail": problem.get("detail"),
                "request_id": request.headers.get("x-request-id")
                or request.scope.get("request_id"),
            },
        )

        return _problem_response(problem, headers=exc.headers)

    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
