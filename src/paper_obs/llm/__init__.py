"""The model layer: what a model is, and how a provider is reached.

This package is the only place in the lab that knows a model exists. It imports
nothing from ``domain``, ``geometry`` or ``search``, and none of those three imports
anything from here — that boundary is the project's main architectural claim, and
it is what lets a provider, or a whole workflow, be replaced without touching the
engine.

This package holds no client: a provider is reached through LangChain, from a
``ModelConfig`` and the key this module resolves. What is left here is pure data on the
standard library, so the API can list the providers without the ``agents`` extra.
"""

from .models import (
    DEFAULT_PROVIDER,
    ENVIRONMENT_KEY,
    PROVIDERS,
    REASONING_EFFORTS,
    ModelConfig,
    Provider,
    catalogue,
    endpoint_for,
    key_present,
    provider,
    resolve_api_key,
)
from .redaction import forget, install_log_scrubber, redact, redact_document, remember

__all__ = [
    "DEFAULT_PROVIDER",
    "ENVIRONMENT_KEY",
    "PROVIDERS",
    "REASONING_EFFORTS",
    "ModelConfig",
    "Provider",
    "catalogue",
    "endpoint_for",
    "key_present",
    "provider",
    "redact",
    "redact_document",
    "remember",
    "forget",
    "install_log_scrubber",
    "resolve_api_key",
]
