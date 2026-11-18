"""Domain Service integrity exceptions."""

class IntegrityViolation(ValueError):
    """Raised when a requested write breaks a domain integrity rule."""


class DomainError(Exception):
    """Base class for errors safe to translate to an API response."""


class NotFound(DomainError):
    pass


class Conflict(DomainError):
    pass


class PolicyUnavailable(DomainError):
    pass


class InvalidRequest(DomainError):
    pass
