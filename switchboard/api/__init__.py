"""Switchboard API layer — the FastAPI app and its cross-cutting concerns.

This package holds the HTTP surface: the token gate (`auth`), the timing +
correlation-id middleware (`timing`), the exception handlers that render the uniform
error envelope (`error_handlers`), the capability-shaped routes (`routes/`), and the
app factory (`main`). It dispatches to integration modules through their uniform
interface and wraps every response in the uniform envelope; it knows no vendor
specifics.
"""

from __future__ import annotations
