"""Domain Service integrity exceptions."""

class IntegrityViolation(ValueError):
    """Raised when a requested write breaks a domain integrity rule."""
