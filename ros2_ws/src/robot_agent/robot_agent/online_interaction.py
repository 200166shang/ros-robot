"""在线文本交互主链路：单回合、先校验后执行、结果确认后回复。"""

import json
import math
import threading
import uuid
from queue import Empty, Queue
from typing import Dict

from .online_actions import ActionRegistry
from .online_provider import TextProvider


class OperationTimeout(Exception):
    """已提交操作在期限内未得到结果。"""


def _unique_object(pairs):
    """拒绝重复 JSON 键，避免模型输出存在歧义。"""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("重复 JSON 键")
        result[key] = value
    return result


class OnlineInteraction:
    """通过 submit 暴露完整回合；超时后在途动作结束前仍保持忙状态。"""

    def __init__(
        self,
        provider: TextProvider,
        actions: ActionRegistry,
        provider_timeout: float = 60.0,
        action_timeout: float = 5.0,
    ) -> None:
        """保存 provider/设备 Adapters 以及有限的执行期限。"""
        for timeout in (provider_timeout, action_timeout):
            if not math.isfinite(timeout) or timeout <= 0:
                raise ValueError("超时必须为正有限秒数")
        self._provider = provider
        self._actions = actions
        self._provider_timeout = provider_timeout
        self._action_timeout = action_timeout
        self._lock = threading.Lock()
        self._inflight = threading.Event()
        self._inflight.set()

    def submit(self, text: str) -> Dict:
        """提交文本，返回关联标识、回复、动作结果与回合终态；忙时立即拒绝。"""
        turn_id = uuid.uuid4().hex
        result = {"turn_id": turn_id, "status": "failed", "reply": "", "actions": []}
        if not self._lock.acquire(blocking=False):
            return dict(result, status="busy", reply="正在处理上一回合，请稍后再试。")
        try:
            if not self._inflight.is_set():
                return dict(result, status="busy", reply="上一回合的调用结果仍未知，请稍后再试。")
            if not isinstance(text, str) or not text.strip() or len(text) > 8192:
                return dict(result, status="rejected", reply="文本为空或过长。")

            # 1. 收齐 provider 输出；流式片段只拼接，绝不触发动作。
            raw = self._bounded(
                lambda: self._collect(text),
                self._provider_timeout,
            )
            payload = json.loads(raw, object_pairs_hook=_unique_object)
            if not isinstance(payload, dict):
                raise ValueError("模型输出必须为对象")
            if set(payload) == {"function", "response"}:
                functions, response = payload["function"], payload["response"]
            elif set(payload) == {"fc", "res"}:
                functions, response = payload["fc"], payload["res"]
            else:
                raise ValueError("模型输出字段不兼容")
            if not isinstance(response, str) or not response.strip():
                raise ValueError("模型回复无效")

            # 2. 全表动作与参数校验通过后，才允许发出第一个动作。
            commands = self._actions.validate(functions)
            result["actions"] = [
                {"name": name, "parameters": parameters, "status": "not_executed"}
                for name, parameters in commands
            ]

            # 3. 按序执行并保留有意重复；异常或超时停止，绝不自动重试。
            for action in result["actions"]:
                try:
                    receipt = self._bounded(
                        lambda: self._actions.execute(action["name"], action["parameters"]),
                        self._action_timeout,
                    )
                except OperationTimeout:
                    receipt = {"status": "unknown", "detail": "已发出调用超时，执行结果未知"}
                except Exception:
                    receipt = {"status": "unknown", "detail": "执行异常，无法确认设备结果"}
                action.update(status=receipt["status"], detail=receipt.get("detail", ""))
                if action["status"] not in {"simulated_success", "real_success"}:
                    break

            # 4. 动作回复只取已确认结果，不采用模型执行前的成功承诺。
            if not commands:
                return dict(result, status="completed", reply=response)
            labels = {
                "simulated_success": "模拟成功",
                "real_success": "真实接口确认成功",
                "failed": "失败",
                "unknown": "结果未知",
                "not_executed": "未执行",
            }
            result["reply"] = (
                "；".join(
                    action["name"] + "：" + labels[action["status"]] for action in result["actions"]
                )
                + "。"
            )
            result["status"] = (
                "completed"
                if all(
                    a["status"] in {"simulated_success", "real_success"} for a in result["actions"]
                )
                else "failed"
            )
            return result
        except OperationTimeout:
            return dict(result, reply="在线模型超时，本轮未发出动作。")
        except (ValueError, TypeError, SyntaxError):
            return dict(result, status="rejected", reply="模型输出或动作参数无效，全部动作未执行。")
        except Exception:
            return dict(result, reply="在线模型不可用，本轮未发出动作。")
        finally:
            self._lock.release()

    def _collect(self, text: str) -> str:
        """接受完整字符串或增量字符串流，并限制总输出大小。"""
        output = self._provider.complete(text, self._provider_timeout)
        chunks = [output] if isinstance(output, str) else output
        raw = ""
        for chunk in chunks:
            if not isinstance(chunk, str):
                raise ValueError("流式片段不是字符串")
            raw += chunk
            if len(raw.encode("utf-8")) > 65536:
                raise ValueError("模型输出过长")
        return raw

    def _bounded(self, operation, timeout: float):
        """限制等待时间；保留在途标识，避免超时动作与下一轮重叠。"""
        outcomes = Queue(maxsize=1)
        self._inflight.clear()

        def run():
            """把结果或异常交还主链路，并释放在途标识。"""
            try:
                value = operation()
                self._inflight.set()
                outcomes.put((True, value))
            except Exception as error:
                self._inflight.set()
                outcomes.put((False, error))

        threading.Thread(target=run, daemon=True).start()
        try:
            success, value = outcomes.get(timeout=timeout)
        except Empty:
            raise OperationTimeout() from None
        if not success:
            raise value
        return value
