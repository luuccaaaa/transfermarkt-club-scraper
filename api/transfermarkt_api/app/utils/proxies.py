from __future__ import annotations

from itertools import cycle
from pathlib import Path
from threading import Lock
from typing import Optional


class ProxyManager:
    def __init__(self, file_path: Optional[Path] = None) -> None:
        root_dir = Path(__file__).resolve().parents[2]
        self._file_path = file_path or root_dir / "proxies.txt"
        self._lock = Lock()
        self._last_mtime: Optional[float] = None
        self._proxies: list[str] = []
        self._proxy_cycle = None

    def _refresh(self) -> None:
        if not self._file_path.exists():
            self._proxies = []
            self._proxy_cycle = None
            self._last_mtime = None
            return

        current_mtime = self._file_path.stat().st_mtime
        if self._last_mtime == current_mtime and self._proxy_cycle:
            return

        with self._file_path.open(encoding="utf-8") as file:
            proxies = [line.strip() for line in file if line.strip() and not line.lstrip().startswith("#")]

        self._proxies = proxies
        self._last_mtime = current_mtime
        self._proxy_cycle = cycle(self._proxies) if self._proxies else None

    def get_all(self) -> list[str]:
        with self._lock:
            self._refresh()
            return list(self._proxies)

    def get_next(self) -> Optional[str]:
        with self._lock:
            self._refresh()
            if not self._proxy_cycle:
                return None
            try:
                return next(self._proxy_cycle)
            except StopIteration:
                # cycle should not raise StopIteration, but reset if it ever happens
                self._proxy_cycle = cycle(self._proxies) if self._proxies else None
                return next(self._proxy_cycle) if self._proxy_cycle else None


_proxy_manager = ProxyManager()


def get_proxy_manager() -> ProxyManager:
    return _proxy_manager


def get_proxy_list() -> list[str]:
    return _proxy_manager.get_all()


def get_next_proxy() -> Optional[str]:
    return _proxy_manager.get_next()
