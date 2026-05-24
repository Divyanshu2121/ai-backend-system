from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import ORJSONResponse

from app.core.logging import get_logger

logger = get_logger(__name__)


# ── Domain Exceptions ────────────────────────────────────────────────────────


class AppException(Exception):
    """Base exception for all application errors."""

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    error_code: str = "INTERNAL_ERROR"
    message: str = "An unexpected error occurred"

    def __init__(self, message: str | None = None, detail: Any = None) -> None:
        self.message = message or self.__class__.message
        self.detail = detail
        super().__init__(self.message)


class NotFoundError(AppException):
    status_code = status.HTTP_404_NOT_FOUND
    error_code = "NOT_FOUND"
    message = "Resource not found"


class ValidationError(AppException):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    error_code = "VALIDATION_ERROR"
    message = "Validation failed"


class AuthenticationError(AppException):
    status_code = status.HTTP_401_UNAUTHORIZED
    error_code = "AUTHENTICATION_FAILED"
    message = "Authentication failed"


class AuthorizationError(AppException):
    status_code = status.HTTP_403_FORBIDDEN
    error_code = "FORBIDDEN"
    message = "You do not have permission to perform this action"


class ConflictError(AppException):
    status_code = status.HTTP_409_CONFLICT
    error_code = "CONFLICT"
    message = "Resource already exists"


class RateLimitError(AppException):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    error_code = "RATE_LIMIT_EXCEEDED"
    message = "Too many requests. Please slow down."


class DataIngestionError(AppException):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    error_code = "INGESTION_FAILED"
    message = "Data ingestion failed"


class SchemaGenerationError(AppException):
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    error_code = "SCHEMA_GENERATION_FAILED"
    message = "Schema generation failed"


class AIServiceError(AppException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    error_code = "AI_SERVICE_ERROR"
    message = "AI service unavailable or returned an error"


class QueryExecutionError(AppException):
    status_code = status.HTTP_400_BAD_REQUEST
    error_code = "QUERY_EXECUTION_FAILED"
    message = "Query execution failed"


# ── Error Response Builder ────────────────────────────────────────────────────


def _error_response(
    status_code: int,
    error_code: str,
    message: str,
    detail: Any = None,
) -> ORJSONResponse:
    body: dict[str, Any] = {
        "success": False,
        "error": {
            "code": error_code,
            "message": message,
        },
    }
    if detail is not None:
        body["error"]["detail"] = detail
    return ORJSONResponse(status_code=status_code, content=body)


# ── FastAPI Exception Handlers ───────────────────────────────────────────────


def register_exception_handlers(app: FastAPI) -> None:

    @app.exception_handler(AppException)
    async def app_exception_handler(
        request: Request, exc: AppException
    ) -> ORJSONResponse:
        logger.warning(
            "Application error",
            error_code=exc.error_code,
            message=exc.message,
            path=str(request.url),
        )
        return _error_response(
            exc.status_code, exc.error_code, exc.message, exc.detail
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> ORJSONResponse:
        errors = [
            {"field": ".".join(str(loc) for loc in err["loc"]), "msg": err["msg"]}
            for err in exc.errors()
        ]
        logger.warning("Request validation error", errors=errors, path=str(request.url))
        return _error_response(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "VALIDATION_ERROR",
            "Request validation failed",
            errors,
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request, exc: Exception
    ) -> ORJSONResponse:
        logger.error(
            "Unhandled exception",
            exc_info=exc,
            path=str(request.url),
        )
        return _error_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "INTERNAL_ERROR",
            "An unexpected error occurred",
        )
