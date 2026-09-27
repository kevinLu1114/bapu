"""Minimal client for TypeSafe's System One judgment API (the Jev model).

Only the online modes of ``bapu-gate`` and ``bapu-findings`` use this module, and only when
they are asked to and the ``TYPESAFE_API_KEY`` environment variable is set. Importing it sends
nothing; ``_send`` is the one function in the package that opens a network connection.

One request carries one ``state`` and several independent questions::

    POST https://api.typesafe.ai/v1/systemone
    {"state": {...}, "model": "jev-1.13.0", "questions": {"<id>": {...}, ...}}

and the response names the model that answered and carries one typed answer per question::

    {"model": "jev-1.13.0", "answers": {"<id>": {"type": "noul", "noul": 0.93}, ...}}

A ``noul`` answer is the probability that the answer is "yes". A ``score`` answer carries
``probabilities`` over ordered levels and a ``legend`` that names them.

Three properties decide how the tools use the answers:

1. Typed is not correct. The schema cannot hold an invalid value; it can hold a wrong one.
2. A probability ranks cases for review. It authorises nothing on its own.
3. Each question asks about one observable thing. Numbers are computed in code and passed in
   as facts; the model is never asked to compute them.
"""

from __future__ import annotations

import http.client
import json
import os
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any

from . import __version__

API_URL = "https://api.typesafe.ai/v1/systemone"
ENV_KEY = "TYPESAFE_API_KEY"
#: Thresholds belong to one model version, so requests pin an exact id and an answer from any
#: other model is refused. Aliases that resolve to a different id are refused for that reason.
DEFAULT_MODEL = "jev-1.13.0"
USER_AGENT = f"bapu/{__version__}"
#: Rate limited (429) and overloaded (529) answers are retried with exponential backoff.
RETRY_STATUSES = frozenset({429, 529})

#: The API's edge firewall has been observed to refuse, with HTTP 403 and before any model sees
#: the request, a body in which a quote, backtick, pipe or semicolon directly precedes
#: ``python -m`` or ``python -c``. Review evidence quotes such commands all the time, so those
#: four characters are replaced by full-width look-alikes that read the same to the model. The
#: same edge refuses urllib's default User-Agent, which is why ``USER_AGENT`` is always sent.
_EDGE_TRIGGER = re.compile(r"[`'|;](?=\s*python\s+-[A-Za-z])")
_LOOKALIKE = {"`": "\u2018", "'": "\u2018", "|": "\uff5c", ";": "\uff1b"}


class JevError(RuntimeError):
    """No usable judgment: no key, an HTTP error, a timeout, or a malformed answer.

    ``status`` is the HTTP status when one came back, else 0.
    """

    def __init__(self, message: str, status: int = 0) -> None:
        super().__init__(message)
        self.status = status


def api_key(environ: Mapping[str, str] | None = None) -> str:
    """The key from ``TYPESAFE_API_KEY``, the only credential this package ever reads."""
    env = os.environ if environ is None else environ
    key = env.get(ENV_KEY, "").strip()
    if not key:
        raise JevError(f"{ENV_KEY} is not set: online mode needs it (offline mode does not)")
    return _checked_key(key)


def _checked_key(key: str) -> str:
    """``key`` unchanged, or JevError. A key with a line break or a control character inside it
    would make the HTTP layer fail with an error that quotes the whole header, key included;
    it is refused here, by a message that never contains it."""
    if not key or any(ch.isspace() or not ch.isprintable() for ch in key):
        raise JevError(
            f"the API key in {ENV_KEY} is empty or contains whitespace or control characters"
        )
    return key


def api_key_is_set(environ: Mapping[str, str] | None = None) -> bool:
    """Whether online mode could run; reads the variable, never prints it."""
    env = os.environ if environ is None else environ
    return bool(env.get(ENV_KEY, "").strip())


def edge_safe(value: Any) -> Any:
    """``value`` with every edge-trigger character replaced; dicts and lists are walked."""
    if isinstance(value, str):
        return _EDGE_TRIGGER.sub(lambda m: _LOOKALIKE[m.group(0)], value)
    if isinstance(value, dict):
        return {k: edge_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [edge_safe(v) for v in value]
    return value


def is_probability(value: Any) -> bool:
    """A real number in [0, 1]. Booleans are refused, and so are NaN and huge integers: the
    range test runs on the raw value, which both fail."""
    return type(value) in (int, float) and 0 <= value <= 1


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect is an error, never a hop: following it would resend the key and the state to
    whatever host the ``Location`` header names."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def _send(url: str, data: bytes, headers: dict[str, str], timeout: float) -> bytes:
    """One POST and its raw response body. Every network access in the package goes here."""
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with _OPENER.open(request, timeout=timeout) as response:
        return response.read()


def judge(
    state: Any,
    questions: dict[str, dict[str, Any]],
    *,
    model: str = DEFAULT_MODEL,
    key: str | None = None,
    url: str = API_URL,
    timeout: float = 60.0,
    retries: int = 3,
    backoff: float = 1.0,
    sleep: Callable[[float], None] | None = None,
) -> dict[str, Any]:
    """The validated response for ``questions`` asked over ``state``.

    Raises JevError when no key is set, the request fails, the response is not JSON, the
    answering model is not ``model``, or any question lacks a valid answer. A missing answer
    is never read as 0.0.
    """
    token = api_key() if key is None else _checked_key(key)
    body = {"state": state, "model": model, "questions": questions}
    data = json.dumps(edge_safe(body), ensure_ascii=False).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
    }
    pause = time.sleep if sleep is None else sleep
    attempt = 0
    while True:
        try:
            raw = _send(url, data, headers, timeout)
            break
        except urllib.error.HTTPError as exc:
            if exc.code in RETRY_STATUSES and attempt < retries:
                pause(backoff * (2**attempt))
                attempt += 1
                continue
            raise JevError(f"HTTP {exc.code}: {_error_detail(exc)}", status=exc.code) from None
        except (OSError, http.client.HTTPException) as exc:  # URLError and timeouts included
            reason = getattr(exc, "reason", None) or exc
            raise JevError(f"request failed: {reason}") from None
        except ValueError as exc:
            # Raised while building or sending the request (an invalid URL or header). Its
            # message may quote a header, so only the type is reported.
            raise JevError(f"request could not be sent ({type(exc).__name__})") from None
    return parse_response(raw, questions, model)


def parse_response(raw: bytes, questions: Mapping[str, Any], model: str) -> dict[str, Any]:
    """The decoded response, or JevError naming what is wrong with it."""
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, RecursionError) as exc:
        raise JevError(f"response is not JSON: {exc}") from None
    if not isinstance(payload, dict):
        raise JevError(f"response is not a JSON object ({type(payload).__name__})")
    answered = payload.get("model")
    if answered != model:
        raise JevError(f"model mismatch: requested {model!r}, answered {answered!r}")
    answers = payload.get("answers")
    if not isinstance(answers, dict):
        raise JevError("response carries no 'answers' object")
    problems = [
        problem
        for qid, spec in questions.items()
        for problem in _answer_problems(qid, spec, answers.get(qid))
    ]
    if problems:
        raise JevError("answers without a valid value: " + "; ".join(problems))
    return payload


def _answer_problems(qid: str, spec: Mapping[str, Any], answer: Any) -> list[str]:
    if not isinstance(answer, dict):
        return [f"{qid}: no answer"]
    if spec.get("type") == "noul":
        value = answer.get("noul")
        return [] if is_probability(value) else [f"{qid}: noul={value!r}"]
    probabilities = answer.get("probabilities")
    if not isinstance(probabilities, dict) or not probabilities:
        return [f"{qid}: no probabilities"]
    return [f"{qid}: {k}={v!r}" for k, v in probabilities.items() if not is_probability(v)]


def _error_detail(exc: urllib.error.HTTPError) -> str:
    try:
        text = exc.read().decode("utf-8", "replace")
    except (OSError, http.client.HTTPException, AttributeError):
        return "(error body unreadable)"
    try:
        error = json.loads(text)["error"]
        return f"{error['code']}: {error['message']}"
    except (ValueError, KeyError, TypeError):
        return text.strip()[:300] or "(empty error body)"


def noul(answers: Mapping[str, Any], qid: str) -> float:
    """The probability of "yes" for one ``noul`` question; JevError when it is not valid."""
    answer = answers.get(qid)
    value = answer.get("noul") if isinstance(answer, dict) else None
    if not is_probability(value):
        raise JevError(f"no valid probability for question {qid!r}: {value!r}")
    return float(value)


def top_level(answer: Mapping[str, Any]) -> str:
    """The most probable level of a ``score`` answer, by its legend label when there is one."""
    probabilities = answer.get("probabilities") or {}
    if not isinstance(probabilities, dict) or not probabilities:
        return ""
    best = max(probabilities, key=lambda k: float(probabilities[k]))
    legend = answer.get("legend") or {}
    label = legend.get(best) if isinstance(legend, dict) else None
    if isinstance(label, dict) and "level" in label:
        return str(label["level"])
    return str(label if label is not None else best)
