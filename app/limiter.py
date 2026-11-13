"""Shared rate limiter.

Kept in its own module so routers can import it without importing the app
(which would be a circular import).
"""

from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address, default_limits=[])
