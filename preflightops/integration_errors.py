"""Shared exceptions for optional external integrations."""


class IntegrationError(Exception):
    """Raised when an opt-in integration is unsafe, misconfigured, or fails."""
