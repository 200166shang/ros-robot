"""模型、动作和语音共用的阻塞I/O调用隔离。"""

import asyncio
import threading
from concurrent.futures import Future
from typing import Any, Callable, Optional


def start_call(operation: Callable[[], Any]) -> Future:
    """隔离阻塞 I/O；Future 传回结果，不取消已提交的调用。"""
    call = Future()

    def run() -> None:
        """把 I/O 的结果或异常交给标准 Future，不操作回合业务状态。"""
        try:
            result = operation()
        except Exception as error:
            call.set_exception(error)
        else:
            call.set_result(result)

    threading.Thread(target=run, daemon=True, name="online-agent-io").start()
    return call


class LegacyCall:
    """持有原阻塞调用，等待超时或取消均不冒充调用完成。"""

    def __init__(self) -> None:
        """初始没有在途操作。"""
        self._call: Optional[Future] = None

    @property
    def pending(self) -> bool:
        """原操作结束前保持在途约束。"""
        return self._call is not None and not self._call.done()

    async def run(
        self, operation: Callable[[], Any], timeout: Optional[float] = None
    ) -> Any:
        """隔离一次旧 I/O 并保留其真实完成状态。"""
        if self.pending:
            raise RuntimeError("旧 I/O 操作仍在途")
        self._call = start_call(operation)
        waiter = asyncio.wrap_future(self._call)
        return await asyncio.wait_for(asyncio.shield(waiter), timeout)
