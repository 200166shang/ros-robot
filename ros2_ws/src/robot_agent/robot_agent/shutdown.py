"""退出等待使用调用者的绝对期限，异常保留给拥有者。"""

import asyncio
import time
from typing import Iterable, Optional


class ShutdownError(Exception):
    """多个必要收尾失败；保留所有原始异常供诊断。"""

    def __init__(self, errors: Iterable[BaseException]) -> None:
        """Python3.8不支持异常组，显式保存关闭与记录错误。"""
        self.errors = tuple(errors)
        super().__init__("; ".join(str(error) for error in self.errors))


def observe(task: asyncio.Task) -> None:
    """迟到的本地清理仍由原Task持有，领取异常避免静默丢失。"""
    if not task.cancelled():
        task.exception()


async def finish_tasks(
    tasks: Iterable[asyncio.Task], deadline: Optional[float]
) -> None:
    """等待所有已启动收尾；到期取消本地等待，不新增逐层预算。"""
    owned = tuple(tasks)
    if not owned:
        return
    for task in owned:
        task.add_done_callback(observe)
    _, pending = await asyncio.wait(
        owned,
        timeout=None
        if deadline is None
        else max(0, deadline - time.monotonic()),
    )
    for task in pending:
        task.cancel()
    if pending:
        # 让协作式finally运行；不等待不遵守取消的外部Closer超出预算。
        await asyncio.sleep(0)
    errors = []
    for task in owned:
        if not task.done():
            errors.append(asyncio.TimeoutError("本地资源未在退出期限内释放"))
        elif not task.cancelled():
            error = task.exception()
            if error is not None:
                errors.append(error)
    if errors:
        if len(errors) == 1:
            raise errors[0]
        raise ShutdownError(errors)
