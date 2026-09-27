"""Test doubles for the one network function, ``bapu.jev._send``."""

from __future__ import annotations

import json
from typing import Any, Callable

from bapu import jev


class FakeAPI:
    """Stands in for ``jev._send``. ``answer(qid, question, state)`` returns one answer object;
    every request is recorded with its decoded body."""

    def __init__(self, answer: Callable[[str, dict, Any], Any], model: str = jev.DEFAULT_MODEL):
        self.answer = answer
        self.model = model
        self.requests: list[dict[str, Any]] = []

    def __call__(self, url: str, data: bytes, headers: dict, timeout: float) -> bytes:
        body = json.loads(data.decode("utf-8"))
        self.requests.append({"url": url, "body": body, "headers": headers, "timeout": timeout})
        answers = {
            qid: self.answer(qid, question, body["state"])
            for qid, question in body["questions"].items()
        }
        return json.dumps({"model": self.model, "answers": answers}).encode("utf-8")


def noul(p: float) -> dict:
    return {"type": "noul", "noul": p}


def raiser(exc: BaseException) -> Callable[..., bytes]:
    def send(*args: Any, **kwargs: Any) -> bytes:
        raise exc

    return send
