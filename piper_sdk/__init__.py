# piper_sdk/__init__.py

from .client import (
    PiperClient,
    PiperError,
    PiperConfigError,
    PiperLinkNeededError,
    PiperAuthError,
    PiperGrantError, # Added
    PiperGrantNeededError, # Now inherits from PiperGrantError
    PiperForbiddenError, # Added
    PiperRawSecretExchangeError 
)

__version__ = "0.4.2" # <-- UPDATE THIS

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
    "__version__"
]