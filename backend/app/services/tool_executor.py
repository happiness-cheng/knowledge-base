"""有界只读工具执行：超时不等待线程退出；任务真正完成才释放容量。"""
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from copy import deepcopy
from threading import BoundedSemaphore, Lock
from typing import Any

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


class ToolWaitTimeout(TimeoutError):
    pass


class ToolCapacityUnavailable(RuntimeError):
    pass


class BoundedToolExecutor:
    def __init__(self, capacity: int = 4, *, slots: BoundedSemaphore | None = None):
        self._slots = slots if slots is not None else BoundedSemaphore(capacity)
        self._pool = ThreadPoolExecutor(max_workers=capacity, thread_name_prefix='kb-tool')

    def run(self, handler: Any, arguments: dict, sessions: Any, *, user_id: int, timeout: float) -> str:
        arguments = deepcopy(arguments)
        if not self._slots.acquire(blocking=False):
            raise ToolCapacityUnavailable('tool capacity unavailable')

        def invoke():
            if sessions is None:
                return handler(arguments, None, user_id=user_id)
            with sessions() as tool_db:
                return handler(arguments, tool_db, user_id=user_id)

        try:
            future = self._pool.submit(invoke)
        except Exception:
            self._slots.release()
            raise
        future.add_done_callback(lambda _future: self._slots.release())
        try:
            result = future.result(timeout=timeout)
        except FutureTimeout:
            if future.done():
                raise  # 工具自身TimeoutError，交给普通失败分类。
            future.cancel()  # 只能取消尚未开始的工作，不能杀死正在运行的线程。
            raise ToolWaitTimeout() from None
        if not isinstance(result, str):
            raise TypeError('tool result must be a JSON string')
        return result

    def close(self, *, wait: bool = False) -> None:
        self._pool.shutdown(wait=wait, cancel_futures=True)


_slots = BoundedSemaphore(4)
_lock = Lock()
_executor: BoundedToolExecutor | None = None


def _get_executor() -> BoundedToolExecutor:
    global _executor
    with _lock:
        if _executor is None:
            _executor = BoundedToolExecutor(slots=_slots)
        return _executor


def close_tool_executor(*, wait: bool = False) -> None:
    global _executor
    with _lock:
        previous, _executor = _executor, None
    if previous is not None:
        previous.close(wait=wait)


def run_read_tool(handler: Any, arguments: dict, db: Any, *, user_id: int, timeout: float) -> str:
    sessions = None
    if isinstance(db, Session):
        if db.new or db.dirty or db.deleted:
            raise ValueError('tool requires committed database state')
        bind = db.get_bind()
        if not isinstance(bind, Engine) or isinstance(bind.pool, StaticPool) or (
            bind.dialect.name == 'sqlite' and (
                bind.url.database in {None, '', ':memory:'} or bind.url.query.get('mode') == 'memory'
            )
        ):
            # 内存SQLite/单连接事务不能异步复制连接；同步执行不宣称硬超时。
            return handler(deepcopy(arguments), db, user_id=user_id)
        sessions = sessionmaker(bind=bind, autoflush=False)
    return _get_executor().run(handler, arguments, sessions, user_id=user_id, timeout=timeout)
