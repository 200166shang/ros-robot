"""模型、动作和语音共用的阻塞I/O调用隔离。"""

import threading
from concurrent.futures import Future
from typing import Any, Callable


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
