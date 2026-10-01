"""Keeping a key out of everything the lab writes, answers with or logs.

A key is resolved when a call is made and lives only in the client that makes it, but an
exception message can quote the request it failed on, a run document can carry a settings
value someone pasted a key into, and a library can log a header. :func:`redact` is the one
place that knows what a secret looks like, and every artefact the lab produces passes
through it: a run document before it is written, an API error detail before it is returned,
and every log record at the moment it is created.

The exact key of a run is remembered only while the run is going, in this process memory,
so it can be scrubbed even when it has no recognisable prefix; :func:`forget` drops it when
the run ends. Nothing here imports an HTTP library or a framework, so the API can scrub its
answers without the agents extra.
"""

from __future__ import annotations

import logging
import re
from threading import Lock
from typing import Any

#: What replaces a secret.
PLACEHOLDER = "[redacted]"

#: Key-shaped strings, for a key this process never resolved itself: a pasted line, a
#: logged header, a traceback. The prefixes are the ones the provider rows use; a key with
#: no prefix at all is still caught when it is the run's own, because it is remembered.
_SHAPES = re.compile(
    r"(?i)("
    r"bearer\s+[A-Za-z0-9._\-+/=]{8,}"
    r"|sk-[A-Za-z0-9._\-]{6,}"
    r"|gsk_[A-Za-z0-9]{16,}"
    r"|xai-[A-Za-z0-9]{16,}"
    r"|AIza[A-Za-z0-9_\-]{16,}"
    r"|hf_[A-Za-z0-9]{16,}"
    r"|r8_[A-Za-z0-9]{16,}"
    r")"
)

_lock = Lock()
_remembered: set[str] = set()


def remember(secret: str | None) -> None:
    """Keep one exact secret in memory until :func:`forget` drops it."""
    if secret:
        with _lock:
            _remembered.add(secret)


def forget(secret: str | None) -> None:
    """Drop a secret kept by :func:`remember`."""
    if secret:
        with _lock:
            _remembered.discard(secret)


def _secrets(extra: tuple[str, ...]) -> tuple[str, ...]:
    """Return the exact secrets to replace, longest first so a fragment never wins."""
    with _lock:
        known = tuple(_remembered)
    return tuple(sorted({value for value in (*extra, *known) if value}, key=len, reverse=True))


def redact(text: str, *, secrets: tuple[str, ...] = ()) -> str:
    """Return ``text`` with every exact or key-shaped secret replaced.

    ``secrets`` names the keys this call already knows — the one a request carried — while
    the module remembers the keys of the runs currently going.
    """
    if not text:
        return text
    for secret in _secrets(secrets):
        text = text.replace(secret, PLACEHOLDER)
    return _SHAPES.sub(PLACEHOLDER, text)


def redact_document(value: Any, *, secrets: tuple[str, ...] = ()) -> Any:
    """Return ``value`` with every string in it — mapping keys included — redacted.

    A run document is a tree of JSON values, and a key can hide in any of them: an error
    message, a settings value, a base URL carrying a query parameter. Redacting the whole
    tree before it is written is cheaper than proving no leaf can carry a secret.
    """
    if isinstance(value, str):
        return redact(value, secrets=secrets)
    if isinstance(value, dict):
        return {
            redact(str(key), secrets=secrets): redact_document(item, secrets=secrets)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact_document(item, secrets=secrets) for item in value]
    return value


def _redact_args(args: Any) -> Any:
    """Return logging arguments with their strings redacted, preserving their shape."""
    if isinstance(args, str):
        return redact(args)
    if isinstance(args, tuple):
        return tuple(_redact_args(item) for item in args)
    if isinstance(args, dict):
        return {key: _redact_args(item) for key, item in args.items()}
    return args


_installed = False


def install_log_scrubber() -> None:
    """Make every log record created afterwards pass through :func:`redact`. Idempotent.

    A filter on a logger misses records propagated from its children, and a filter on a
    handler misses handlers added later, so the scrubber wraps the record factory instead:
    it sees every record, whoever logs it and wherever it goes. An already-formatted
    traceback is beyond reach — which is why the lab records no traceback of its own.
    """
    global _installed
    if _installed:
        return
    _installed = True
    previous = logging.getLogRecordFactory()

    def factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = previous(*args, **kwargs)
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        record.args = _redact_args(record.args)
        return record

    logging.setLogRecordFactory(factory)


__all__ = [
    "PLACEHOLDER",
    "forget",
    "install_log_scrubber",
    "redact",
    "redact_document",
    "remember",
]
