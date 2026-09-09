"""Tests for the PyPI name check.

Every test stubs `urlopen`: the suite must stay hermetic, and a real request
would make results depend on what happens to be registered today.
"""

from __future__ import annotations

import email.message
import urllib.error
from typing import Any, Self

import pytest

from wheelforge.pypi import DEFAULT_TIMEOUT, NameStatus, check_name


class FakeResponse:
    """The sliver of `HTTPResponse` that `check_name` touches."""

    def __init__(self, status: int) -> None:
        self.status = status

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc) -> None:
        return None


@pytest.fixture
def calls(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """Capture urlopen calls and let each test say what the index replies."""
    seen: list[dict[str, object]] = []
    reply: dict[str, object] = {"response": FakeResponse(200)}

    def fake_urlopen(request: Any, timeout: Any | None = None) -> object:  # pyrefly: ignore[explicit-any]
        seen.append({"request": request, "timeout": timeout})
        outcome = reply["response"]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr("wheelforge.pypi.urllib.request.urlopen", fake_urlopen)
    return seen, reply


def http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        url="https://pypi.org/simple/demo/",
        code=code,
        msg="",
        hdrs=email.message.Message(),
        fp=None,
    )


class TestStatus:
    def test_200_means_the_name_is_taken(
        self, calls: tuple[list[dict[str, object]], dict[str, object]]
    ) -> None:
        _, reply = calls
        reply["response"] = FakeResponse(200)
        assert check_name("demo-bin") is NameStatus.TAKEN

    def test_404_means_the_name_is_available(
        self, calls: tuple[list[dict[str, object]], dict[str, object]]
    ) -> None:
        _, reply = calls
        reply["response"] = http_error(404)
        assert check_name("demo-bin") is NameStatus.AVAILABLE

    @pytest.mark.parametrize("code", [403, 429, 500, 503])
    def test_other_http_codes_are_unknown(
        self, calls: tuple[list[dict[str, object]], dict[str, object]], code: int
    ) -> None:
        """A rate limit or outage must never read as `available`."""
        _, reply = calls
        reply["response"] = http_error(code)
        assert check_name("demo-bin") is NameStatus.UNKNOWN

    @pytest.mark.parametrize(
        "failure",
        [
            urllib.error.URLError("no route to host"),
            TimeoutError("timed out"),
            OSError("connection reset"),
            ValueError("unknown url type"),
        ],
    )
    def test_network_failures_are_unknown(
        self,
        calls: tuple[list[dict[str, object]], dict[str, object]],
        failure: Exception,
    ) -> None:
        """Building offline is supported, so this can never raise."""
        _, reply = calls
        reply["response"] = failure
        assert check_name("demo-bin") is NameStatus.UNKNOWN

    def test_an_unexpected_success_code_is_unknown(
        self, calls: tuple[list[dict[str, object]], dict[str, object]]
    ) -> None:
        _, reply = calls
        reply["response"] = FakeResponse(204)
        assert check_name("demo-bin") is NameStatus.UNKNOWN


class TestRequest:
    def test_asks_the_simple_index_for_the_name(
        self,
        calls: tuple[list[dict[str, Any]], dict[str, object]],  # pyrefly: ignore[explicit-any]
    ) -> None:
        seen, _ = calls
        _ = check_name("demo-bin")
        assert seen[0]["request"].full_url == "https://pypi.org/simple/demo-bin/"

    def test_uses_head_so_no_body_is_fetched(
        self,
        calls: tuple[list[dict[str, Any]], dict[str, object]],  # pyrefly: ignore[explicit-any]
    ) -> None:
        seen, _ = calls
        _ = check_name("demo-bin")
        assert seen[0]["request"].get_method() == "HEAD"

    def test_identifies_itself(
        self,
        calls: tuple[list[dict[str, Any]], dict[str, object]],  # pyrefly: ignore[explicit-any]
    ) -> None:
        seen, _ = calls
        _ = check_name("demo-bin")
        assert "wheelforge" in seen[0]["request"].get_header("User-agent")

    def test_a_timeout_is_always_set(
        self,
        calls: tuple[list[dict[str, Any]], dict[str, object]],  # pyrefly: ignore[explicit-any]
    ) -> None:
        """Without one, a hung index would hang the build."""
        seen, _ = calls
        _ = check_name("demo-bin")
        assert seen[0]["timeout"] == pytest.approx(DEFAULT_TIMEOUT)

    def test_the_timeout_is_overridable(
        self,
        calls: tuple[list[dict[str, Any]], dict[str, object]],  # pyrefly: ignore[explicit-any]
    ) -> None:
        seen, _ = calls
        _ = check_name("demo-bin", timeout=0.5)
        assert seen[0]["timeout"] == pytest.approx(0.5)

    def test_names_are_url_quoted(
        self,
        calls: tuple[list[dict[str, Any]], dict[str, object]],  # pyrefly: ignore[explicit-any]
    ) -> None:
        """Normalisation should prevent this, but the URL is built defensively."""
        seen, _ = calls
        _ = check_name("../etc/passwd")
        assert (
            seen[0]["request"].full_url
        ) == "https://pypi.org/simple/..%2Fetc%2Fpasswd/"
