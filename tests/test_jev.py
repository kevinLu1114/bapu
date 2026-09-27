from __future__ import annotations

import http.server
import io
import json
import threading
import urllib.error

import pytest

from bapu import jev
from helpers import FakeAPI, noul, raiser

QUESTIONS = {"q": {"type": "noul", "instructions": "Is it?"}}


def test_api_key_comes_only_from_the_environment():
    assert jev.api_key({jev.ENV_KEY: "  placeholder \n"}) == "placeholder"
    assert jev.api_key_is_set({jev.ENV_KEY: "placeholder"})
    for environ in ({}, {jev.ENV_KEY: ""}, {jev.ENV_KEY: "   "}):
        assert not jev.api_key_is_set(environ)
        with pytest.raises(jev.JevError, match=jev.ENV_KEY):
            jev.api_key(environ)


@pytest.mark.parametrize(
    "key", ["head\ntail", "head tail", "head\x00tail"], ids=["newline", "space", "control"]
)
def test_a_malformed_key_is_refused_without_being_echoed(key):
    with pytest.raises(jev.JevError) as caught:
        jev.api_key({jev.ENV_KEY: key})
    assert "head" not in str(caught.value) and "tail" not in str(caught.value)
    with pytest.raises(jev.JevError) as caught:
        jev.judge({}, QUESTIONS, key=key)
    assert "head" not in str(caught.value) and "tail" not in str(caught.value)


def test_an_unsendable_request_does_not_echo_the_error(monkeypatch):
    monkeypatch.setattr(jev, "_send", raiser(ValueError("Invalid header value b'Bearer SECRET'")))
    with pytest.raises(jev.JevError) as caught:
        jev.judge({}, QUESTIONS, key="placeholder")
    assert "SECRET" not in str(caught.value)
    assert "could not be sent (ValueError)" in str(caught.value)


def test_judge_without_a_key_sends_nothing():
    # The autouse fixture refuses the network; a JevError (not an AssertionError) proves the
    # missing key stopped the call before any request was attempted.
    with pytest.raises(jev.JevError, match="not set"):
        jev.judge({}, QUESTIONS)


def test_judge_sends_one_pinned_request(fake_api):
    api = fake_api(lambda qid, q, state: noul(0.8))
    payload = jev.judge({"claim": "x"}, QUESTIONS)
    assert payload["answers"]["q"]["noul"] == 0.8
    (request,) = api.requests
    assert request["url"] == jev.API_URL
    assert request["headers"]["Authorization"] == "Bearer placeholder"
    assert request["headers"]["User-Agent"] == jev.USER_AGENT
    assert request["headers"]["Content-Type"] == "application/json"
    assert request["body"] == {
        "state": {"claim": "x"},
        "model": jev.DEFAULT_MODEL,
        "questions": QUESTIONS,
    }


def test_edge_safe_replaces_only_the_triggering_characters():
    text = "run `python -m pytest` | python -c 'x'; python -m http && python -m ok; python3 -m y"
    safe = jev.edge_safe({"a": [text], "n": 3})
    assert safe["n"] == 3
    out = safe["a"][0]
    assert "`python -m" not in out and "| python -c" not in out and "; python -m" not in out
    assert "\u2018python -m pytest" in out
    assert "\uff5c python -c" in out
    assert "&& python -m ok" in out  # not a trigger
    assert "; python3 -m y" in out  # python3 is not a trigger


def test_body_is_edge_safe_on_the_wire(fake_api):
    api = fake_api(lambda qid, q, state: noul(0.5))
    jev.judge({"evidence": "$ echo hi | python -c 'print(1)'"}, QUESTIONS)
    assert api.requests[0]["body"]["state"]["evidence"] == "$ echo hi \uff5c python -c 'print(1)'"


def _http_error(code: int, body: bytes = b"") -> urllib.error.HTTPError:
    return urllib.error.HTTPError(jev.API_URL, code, "error", {}, io.BytesIO(body))


def test_rate_limit_is_retried_then_succeeds(monkeypatch):
    calls = []

    def send(url, data, headers, timeout):
        calls.append(1)
        if len(calls) < 3:
            raise _http_error(429)
        return json.dumps({"model": jev.DEFAULT_MODEL, "answers": {"q": noul(0.9)}}).encode()

    monkeypatch.setattr(jev, "_send", send)
    delays = []
    payload = jev.judge({}, QUESTIONS, key="placeholder", sleep=delays.append)
    assert payload["answers"]["q"]["noul"] == 0.9
    assert delays == [1.0, 2.0]


def test_retries_are_bounded_and_other_errors_are_not_retried(monkeypatch):
    monkeypatch.setattr(jev, "_send", raiser(_http_error(529)))
    delays = []
    with pytest.raises(jev.JevError) as caught:
        jev.judge({}, QUESTIONS, key="placeholder", retries=2, sleep=delays.append)
    assert caught.value.status == 529 and len(delays) == 2

    body = json.dumps({"error": {"code": "unauthorized", "message": "bad key"}}).encode()
    monkeypatch.setattr(jev, "_send", raiser(_http_error(401, body)))
    delays.clear()
    with pytest.raises(jev.JevError, match="HTTP 401: unauthorized: bad key"):
        jev.judge({}, QUESTIONS, key="placeholder", sleep=delays.append)
    assert delays == []


def test_connection_failure_is_a_jev_error(monkeypatch):
    monkeypatch.setattr(jev, "_send", raiser(urllib.error.URLError("connection refused")))
    with pytest.raises(jev.JevError, match="request failed: connection refused"):
        jev.judge({}, QUESTIONS, key="placeholder")


@pytest.mark.parametrize(
    "raw, message",
    [
        (b"not json", "not JSON"),
        (b"[1, 2]", "not a JSON object"),
        (json.dumps({"model": "jev-other", "answers": {"q": noul(0.9)}}).encode(), "mismatch"),
        (json.dumps({"model": jev.DEFAULT_MODEL}).encode(), "no 'answers'"),
        (json.dumps({"model": jev.DEFAULT_MODEL, "answers": {}}).encode(), "q: no answer"),
    ],
    ids=["not-json", "not-object", "other-model", "no-answers", "missing-answer"],
)
def test_malformed_responses_are_errors_never_scores(raw, message):
    with pytest.raises(jev.JevError, match=message):
        jev.parse_response(raw, QUESTIONS, jev.DEFAULT_MODEL)


@pytest.mark.parametrize("value", [None, True, False, "0.9", -0.1, 1.5, float("nan"), 10**400])
def test_a_noul_outside_zero_to_one_is_refused(value):
    raw = json.dumps(
        {"model": jev.DEFAULT_MODEL, "answers": {"q": {"noul": value}}}, allow_nan=True
    ).encode()
    with pytest.raises(jev.JevError, match="without a valid value"):
        jev.parse_response(raw, QUESTIONS, jev.DEFAULT_MODEL)
    with pytest.raises(jev.JevError):
        jev.noul({"q": {"noul": value}}, "q")


def test_score_answers_need_valid_probabilities_and_report_the_top_level():
    questions = {"s": {"type": "score", "criteria": [{"level": "low"}, {"level": "high"}]}}
    good = {
        "probabilities": {"0": 0.2, "1": 0.8},
        "legend": {"0": {"level": "low"}, "1": {"level": "high"}},
    }
    raw = json.dumps({"model": jev.DEFAULT_MODEL, "answers": {"s": good}}).encode()
    assert jev.parse_response(raw, questions, jev.DEFAULT_MODEL)["answers"]["s"] == good
    assert jev.top_level(good) == "high"
    assert jev.top_level({"probabilities": {"a": 0.1, "b": 0.9}}) == "b"
    assert jev.top_level({}) == ""
    bad = json.dumps({"model": jev.DEFAULT_MODEL, "answers": {"s": {"probabilities": {}}}})
    with pytest.raises(jev.JevError, match="no probabilities"):
        jev.parse_response(bad.encode(), questions, jev.DEFAULT_MODEL)


class _Redirector(http.server.BaseHTTPRequestHandler):
    seen: list = []

    def do_POST(self):  # noqa: N802
        type(self).seen.append((self.path, self.headers.get("Authorization")))
        self.send_response(302)
        self.send_header("Location", "/elsewhere")
        self.send_header("Content-Length", "0")
        self.end_headers()

    do_GET = do_POST  # a client that followed the redirect would be recorded here too

    def log_message(self, *args):
        pass


def test_a_redirect_is_an_error_and_the_key_is_not_resent(monkeypatch):
    # Loopback only: the real transport against a local server that answers every request
    # with a redirect. A client that followed it would reach /elsewhere with the key.
    monkeypatch.setattr(jev, "_send", _REAL_SEND)
    _Redirector.seen = []
    server = http.server.HTTPServer(("127.0.0.1", 0), _Redirector)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/v1/systemone"
        with pytest.raises(jev.JevError, match="HTTP 302"):
            jev.judge({}, QUESTIONS, key="placeholder", url=url, timeout=5)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    assert _Redirector.seen == [("/v1/systemone", "Bearer placeholder")]


_REAL_SEND = jev._send


def test_fake_api_helper_records_what_it_answers(fake_api):
    api = fake_api(lambda qid, q, state: noul(0.7))
    assert isinstance(api, FakeAPI)
    jev.judge({"x": 1}, QUESTIONS)
    assert api.requests[0]["body"]["state"] == {"x": 1}
