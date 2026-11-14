from __future__ import annotations

import fcntl
import os
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import IO
from collections.abc import Callable, Iterator

from archivebox.config.constants import CONSTANTS


class _LifecycleLockState:
    def __init__(self) -> None:
        self.thread_lock = threading.RLock()
        self.users = 0
        self.depth = 0
        self.file: IO[str] | None = None
        self.after_release: list[Callable[[], None]] = []


_registry_lock = threading.Lock()
_registry_pid = os.getpid()
_registry: dict[str, _LifecycleLockState] = {}
_held_locks: ContextVar[tuple[_LifecycleLockState, ...]] = ContextVar("archivebox.lifecycle_locks", default=())


def lifecycle_locks_held() -> bool:
    return _registry_pid == os.getpid() and any(state.depth for state in _held_locks.get())


def after_lifecycle_locks(callback: Callable[[], None]) -> bool:
    """Defer a committed side effect until this operation releases its locks.

    ContextVars follow sync_to_async, so an ORM callback running on a worker
    thread still belongs to the outer crawl owner. This is an in-memory release
    callback, like transaction.on_commit, not another durable task queue.
    """
    with _registry_lock:
        if _registry_pid == os.getpid():
            for state in _held_locks.get():
                if state.depth:
                    state.after_release.append(callback)
                    return True
    return False


def crawl_lifecycle_lock_path(crawl_id: str) -> Path:
    return CONSTANTS.DEFAULT_TMP_DIR / "crawl-locks" / f"{crawl_id}.lock"


@contextmanager
def _lifecycle_lock(key: str, lock_path: Path) -> Iterator[None]:
    global _registry_pid

    with _registry_lock:
        if _registry_pid != os.getpid():
            for inherited_state in _registry.values():
                if inherited_state.file is not None:
                    inherited_state.file.close()
            _registry.clear()
            _registry_pid = os.getpid()
            _held_locks.set(())
        state = _registry.setdefault(key, _LifecycleLockState())
        state.users += 1

    state.thread_lock.acquire()
    context_token = _held_locks.set((*_held_locks.get(), state))
    callbacks: list[Callable[[], None]] = []
    try:
        if state.depth == 0:
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            state.file = lock_path.open("a+", encoding="utf-8")
            try:
                fcntl.flock(state.file.fileno(), fcntl.LOCK_EX)
            except BaseException:
                state.file.close()
                state.file = None
                raise
        state.depth += 1
        try:
            yield
        finally:
            with _registry_lock:
                state.depth -= 1
                if state.depth == 0 and state.file is not None:
                    fcntl.flock(state.file.fileno(), fcntl.LOCK_UN)
                    state.file.close()
                    state.file = None
                    callbacks, state.after_release = state.after_release, []
    finally:
        state.thread_lock.release()
        _held_locks.reset(context_token)
        with _registry_lock:
            state.users -= 1
            if state.users == 0 and state.depth == 0 and _registry.get(key) is state:
                _registry.pop(key, None)
        # Requests and subprocesses may acquire the same lifecycle lock. Run
        # them only after both the file lock and owning thread lock are released.
        for callback in callbacks:
            callback()


@contextmanager
def crawl_lifecycle_lock(crawl_id: str) -> Iterator[None]:
    key = str(crawl_id)
    with _lifecycle_lock(f"crawl:{key}", crawl_lifecycle_lock_path(key)):
        yield


@contextmanager
def binary_lifecycle_lock(binary_id: str) -> Iterator[None]:
    key = str(binary_id)
    lock_path = CONSTANTS.DEFAULT_TMP_DIR / "binary-locks" / f"{key}.lock"
    with _lifecycle_lock(f"binary:{key}", lock_path):
        yield
