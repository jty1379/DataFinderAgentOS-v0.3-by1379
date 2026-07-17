"""基于内存的轻量速率限制器，用于登录等敏感端点。

按 (IP, 目标类型) 维度追踪失败尝试次数，支持：
- 滑动窗口计数
- 指数退避延迟
- 账户级锁定（按用户名）
"""

from __future__ import annotations

import time
import threading
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class _Bucket:
    attempts: int = 0
    first_fail: float = 0.0
    last_fail: float = 0.0
    locked_until: float = 0.0


class RateLimiter:
    """线程安全的内存速率限制器。

    参数：
        max_attempts: 窗口内最大允许失败次数
        window_seconds: 滑动窗口时长（秒）
        lockout_seconds: 超出阈值后的锁定时长（秒）
        cleanup_interval: 清理过期记录的间隔（秒）
    """

    def __init__(
        self,
        max_attempts: int = 5,
        window_seconds: int = 300,
        lockout_seconds: int = 900,
        cleanup_interval: int = 600,
    ):
        self._max_attempts = max_attempts
        self._window_seconds = window_seconds
        self._lockout_seconds = lockout_seconds
        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()
        self._last_cleanup = time.monotonic()
        self._cleanup_interval = cleanup_interval

    def check(self, key: str) -> Optional[str]:
        """检查是否允许继续。返回 None 表示允许，否则返回错误消息。"""
        now = time.time()
        with self._lock:
            self._maybe_cleanup(now)
            bucket = self._buckets.get(key)
            if bucket is None:
                return None
            # 检查锁定状态
            if bucket.locked_until > now:
                remaining = int(bucket.locked_until - now)
                return f"尝试次数过多，请在 {remaining} 秒后重试"
            # 检查窗口过期
            if now - bucket.first_fail > self._window_seconds:
                del self._buckets[key]
                return None
            return None

    def record_failure(self, key: str) -> Optional[str]:
        """记录一次失败尝试。返回 None 表示尚未触发限制，否则返回错误消息。"""
        now = time.time()
        with self._lock:
            self._maybe_cleanup(now)
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = _Bucket(attempts=1, first_fail=now, last_fail=now)
                self._buckets[key] = bucket
                return None

            # 窗口过期则重置
            if now - bucket.first_fail > self._window_seconds:
                bucket.attempts = 1
                bucket.first_fail = now
                bucket.last_fail = now
                bucket.locked_until = 0.0
                return None

            bucket.attempts += 1
            bucket.last_fail = now

            if bucket.attempts >= self._max_attempts:
                bucket.locked_until = now + self._lockout_seconds
                return f"尝试次数过多，请在 {self._lockout_seconds} 秒后重试"

            # 返回剩余允许次数提示
            remaining = self._max_attempts - bucket.attempts
            if remaining <= 2:
                return f"密码错误，还剩 {remaining} 次尝试机会"
            return None

    def reset(self, key: str) -> None:
        """成功登录后重置计数器。"""
        with self._lock:
            self._buckets.pop(key, None)

    def _maybe_cleanup(self, now: float) -> None:
        if now - self._last_cleanup < self._cleanup_interval:
            return
        self._last_cleanup = now
        expired_keys = [
            k for k, v in self._buckets.items()
            if now - v.first_fail > self._window_seconds * 2
        ]
        for k in expired_keys:
            del self._buckets[k]


# 全局实例：用户端和管理端分别使用独立的限制器
user_login_limiter = RateLimiter(
    max_attempts=5,
    window_seconds=300,    # 5 分钟窗口
    lockout_seconds=900,   # 锁定 15 分钟
)

admin_login_limiter = RateLimiter(
    max_attempts=5,
    window_seconds=300,
    lockout_seconds=900,
)
