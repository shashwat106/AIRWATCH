"""Two-level cache for upstream calls: in-memory TTL, then parquet on disk.

If an upstream call fails, the last disk copy is served and marked stale, so the
caller can say so rather than pretend the data is fresh.
"""
from __future__ import annotations

import asyncio
import hashlib
import time
from dataclasses import dataclass
from typing import Awaitable, Callable

import pandas as pd

from .config import CACHE_DIR


@dataclass
class Cached:
    df: pd.DataFrame
    fetched_at: float
    stale: bool = False
    error: str | None = None


_mem: dict[str, Cached] = {}
_locks: dict[str, asyncio.Lock] = {}


def _path(key: str):
    return CACHE_DIR / f"{hashlib.sha1(key.encode()).hexdigest()[:20]}.parquet"


async def cached_df(key: str, ttl: float, fetch: Callable[[], Awaitable[pd.DataFrame]]) -> Cached:
    hit = _mem.get(key)
    if hit and time.time() - hit.fetched_at < ttl:
        return hit
    async with _locks.setdefault(key, asyncio.Lock()):
        hit = _mem.get(key)
        if hit and time.time() - hit.fetched_at < ttl:
            return hit
        path = _path(key)
        if path.exists() and time.time() - path.stat().st_mtime < ttl:
            res = Cached(pd.read_parquet(path), path.stat().st_mtime)
            _mem[key] = res
            return res
        try:
            df = await fetch()
        except Exception as exc:  # upstream down: fall back, and say so
            if path.exists():
                res = Cached(pd.read_parquet(path), path.stat().st_mtime, True, repr(exc)[:200])
                _mem[key] = res
                return res
            raise
        df.to_parquet(path)
        res = Cached(df, time.time())
        _mem[key] = res
        return res
