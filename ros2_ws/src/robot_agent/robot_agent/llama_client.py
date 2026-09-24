"""Small HTTP client for the local llama.cpp completion endpoint."""

import json
from urllib.request import Request, urlopen


class LlamaCompletionClient:
    """Call llama.cpp without coupling model transport to ROS."""

    def __init__(self, endpoint, timeout_seconds=120.0, n_predict=128):
        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds
        self.n_predict = n_predict

    def complete(self, system_prompt, user_prompt):
        prompt = (
            f"System: {system_prompt}<|im_end|>\n"
            f"Human: {user_prompt}<|im_end|>\n"
            "Assistant:"
        )
        payload = {
            "prompt": prompt,
            "temperature": 0.0,
            "seed": 42,
            "n_predict": self.n_predict,
            "stop": ["<|im_end|>"],
            "cache_prompt": False,
        }
        request = Request(
            self.endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=self.timeout_seconds) as response:
            result = json.loads(response.read().decode("utf-8"))
        if not isinstance(result, dict) or not isinstance(result.get("content"), str):
            raise ValueError("llama.cpp returned no completion text")
        return result["content"].strip()
