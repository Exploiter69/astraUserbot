"""Structured error handling and safe user-facing error translation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    """Stable internal failure classes used for logs, jobs, and recovery."""

    UNKNOWN = "UNKNOWN"
    VALIDATION = "VALIDATION"
    AUTHORIZATION = "AUTHORIZATION"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    CONFIGURATION = "CONFIGURATION"
    DEPENDENCY = "DEPENDENCY"
    TIMEOUT = "TIMEOUT"
    RESOURCE = "RESOURCE"
    NETWORK = "NETWORK"
    STORAGE = "STORAGE"
    SUBPROCESS = "SUBPROCESS"
    EXTERNAL = "EXTERNAL"
    INTERNAL = "INTERNAL"


@dataclass(frozen=True, slots=True)
class ErrorContext:
    """Non-sensitive context attached to an error for internal diagnostics."""

    operation: str | None = None
    component: str | None = None
    correlation_id: str | None = None
    retryable: bool = False


class AstraError(Exception):
    """Base exception for controlled Astra failures."""

    code: ErrorCode = ErrorCode.UNKNOWN
    default_message = "The operation could not be completed."
    retryable = False

    def __init__(
        self,
        message: str | None = None,
        *,
        context: ErrorContext | None = None,
        cause: BaseException | None = None,
    ) -> None:
        self.message = _safe_message(message or self.default_message)
        self.context = context or ErrorContext(retryable=self.retryable)
        self.cause = cause
        super().__init__(self.message)


class CommandError(AstraError):
    """Raised when a command fails gracefully and should be reported to the HUD."""

    code = ErrorCode.VALIDATION


class ConfigurationError(AstraError):
    """Raised when critical configuration is missing or invalid."""

    code = ErrorCode.CONFIGURATION


class AuthorizationError(AstraError):
    """Raised when an operation is not authorized."""

    code = ErrorCode.AUTHORIZATION
    default_message = "You are not authorized to perform this operation."


class NotFoundError(AstraError):
    """Raised when a requested resource does not exist."""

    code = ErrorCode.NOT_FOUND
    default_message = "The requested resource was not found."


class ConflictError(AstraError):
    """Raised when an operation conflicts with current state."""

    code = ErrorCode.CONFLICT
    default_message = "The operation conflicts with the current state."


class TimeoutError(AstraError):
    """Controlled timeout failure."""

    code = ErrorCode.TIMEOUT
    default_message = "The operation timed out."
    retryable = True


class ResourceError(AstraError):
    """Raised when a resource limit prevents an operation."""

    code = ErrorCode.RESOURCE
    default_message = "The operation could not run because a resource limit was reached."
    retryable = True


class ExternalServiceError(AstraError):
    """Raised when an external dependency fails."""

    code = ErrorCode.EXTERNAL
    default_message = "An external service is temporarily unavailable."
    retryable = True


def _safe_message(message: Any) -> str:
    """Normalize explicitly supplied user-facing text without exposing exceptions."""
    text = str(message).strip()
    if not text:
        return AstraError.default_message
    # User-facing errors must be bounded. Detailed exception text belongs in logs.
    return text[:500]


def as_astra_error(
    exc: BaseException,
    *,
    operation: str | None = None,
    component: str | None = None,
    correlation_id: str | None = None,
) -> AstraError:
    """Convert arbitrary exceptions into a structured error without exposing details."""
    if isinstance(exc, AstraError):
        return exc
    context = ErrorContext(
        operation=operation,
        component=component,
        correlation_id=correlation_id,
    )
    return AstraError(context=context, cause=exc)


def user_message(exc: BaseException) -> str:
    """Return only the safe message intended for a user-facing surface."""
    if isinstance(exc, AstraError):
        return exc.message
    return AstraError.default_message
