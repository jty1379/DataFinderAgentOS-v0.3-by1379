"""Process-local throttling for authentication endpoints.

The project runs one Tornado process by default.  Failed attempts are tracked
by the peer IP and by a salted hash of ``scope + peer IP + username`` so raw
credentials or account names are never retained in memory.  Deployments with
multiple workers should additionally enforce the same limits at the reverse
proxy or in shared storage.
"""

from __future__ import annotations

import hashlib
import threading
import time
from collections import deque


class AuthenticationRateLimiter:
    WINDOW_SECONDS = 5 * 60
    MAX_FAILURES_PER_PEER = 20
    MAX_FAILURES_PER_ACCOUNT_AND_PEER = 5

    _events: dict[str, deque[float]] = {}
    _lock = threading.Lock()

    @classmethod
    def _digest(cls, *parts: str) -> str:
        value = "\x1f".join(str(part or "").casefold() for part in parts)
        return hashlib.sha256(value.encode("utf-8", errors="ignore")).hexdigest()

    @classmethod
    def _keys(cls, scope: str, peer_ip: str, username: str) -> tuple[str, str]:
        peer = cls._digest("peer", scope, peer_ip)
        account_peer = cls._digest("account-peer", scope, peer_ip, username)
        return peer, account_peer

    @classmethod
    def _prune(cls, events: deque[float], now: float) -> None:
        cutoff = now - cls.WINDOW_SECONDS
        while events and events[0] <= cutoff:
            events.popleft()

    @classmethod
    def retry_after(cls, scope: str, peer_ip: str, username: str) -> int:
        """Return seconds until another expensive authentication is allowed."""
        now = time.monotonic()
        peer_key, account_key = cls._keys(scope, peer_ip, username)
        with cls._lock:
            waits: list[float] = []
            for key, maximum in (
                (peer_key, cls.MAX_FAILURES_PER_PEER),
                (account_key, cls.MAX_FAILURES_PER_ACCOUNT_AND_PEER),
            ):
                events = cls._events.setdefault(key, deque())
                cls._prune(events, now)
                if len(events) >= maximum:
                    waits.append(events[0] + cls.WINDOW_SECONDS - now)
            return max(0, int(max(waits, default=0)) + (1 if waits else 0))

    @classmethod
    def record_failure(cls, scope: str, peer_ip: str, username: str) -> None:
        now = time.monotonic()
        with cls._lock:
            for key in cls._keys(scope, peer_ip, username):
                events = cls._events.setdefault(key, deque())
                cls._prune(events, now)
                events.append(now)

    @classmethod
    def record_success(cls, scope: str, peer_ip: str, username: str) -> None:
        """Clear only the account-specific bucket; keep peer abuse history."""
        _, account_key = cls._keys(scope, peer_ip, username)
        with cls._lock:
            cls._events.pop(account_key, None)

    @classmethod
    def reset_for_tests(cls) -> None:
        with cls._lock:
            cls._events.clear()
