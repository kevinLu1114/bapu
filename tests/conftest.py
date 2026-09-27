"""Shared fixtures. Every test runs offline: the API key is unset and the network is refused."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Callable

import pytest

from bapu import jev
from helpers import FakeAPI

FIXTURES = Path(__file__).parent / "fixtures"

# The fixture project carries its own tests; only the seed-red runner may run them.
collect_ignore = ["fixtures"]


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(jev.ENV_KEY, raising=False)

    def refuse(*args: Any, **kwargs: Any) -> bytes:
        raise AssertionError("a test tried to reach the network")

    monkeypatch.setattr(jev, "_send", refuse)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A private copy of the seed-red fixture project that a test may mutate freely."""
    target = tmp_path / "project"
    shutil.copytree(FIXTURES / "seedred" / "project", target)
    return target


@pytest.fixture
def fake_api(monkeypatch: pytest.MonkeyPatch) -> Callable[..., FakeAPI]:
    """Install a FakeAPI and a placeholder key; returns a factory that takes ``answer``."""

    def install(answer: Callable[[str, dict, Any], Any], model: str = jev.DEFAULT_MODEL) -> FakeAPI:
        api = FakeAPI(answer, model)
        monkeypatch.setenv(jev.ENV_KEY, "placeholder")
        monkeypatch.setattr(jev, "_send", api)
        return api

    return install
