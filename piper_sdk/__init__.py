# piper_sdk/__init__.py

from .client import (
    PiperClient,
    PiperError,
    PiperConfigError,
    PiperLinkNeededError,
    PiperAuthError,
    PiperGrantError,
    PiperGrantNeededError,
    PiperForbiddenError,
    PiperRawSecretExchangeError,
    PiperSecretAcquisitionError # <-- ADDED
)

__version__ = "0.6.0" # <-- UPDATED

__all__ = [
    "PiperClient",
    "PiperError",
    "PiperConfigError",
    "PiperLinkNeededError",
    "PiperAuthError",
    "PiperGrantError",
    "PiperGrantNeededError",
    "PiperForbiddenError",
    "PiperRawSecretExchangeError",
    "PiperSecretAcquisitionError", # <-- ADDED
    "__version__"
]