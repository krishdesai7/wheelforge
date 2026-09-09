"""Tests for the `uv publish` wrapper."""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

import pytest

from wheelforge.errors import PublishError
from wheelforge.publish import (
    TOKEN_ENV,
    plan_publish,
    resolve_token,
    run_publish,
)

if TYPE_CHECKING:
    from pathlib import Path
    from typing import Never

#: Stand-in for a real token. Never reaches a network, only the environment.
FAKE_TOKEN = "pypi-not-a-real-secret"  # ruff: ignore[hardcoded-password-string]


@pytest.fixture
def wheel(tmp_path: Path) -> Path:
    path = tmp_path / "demo_bin-1.0.0-py3-none-any.whl"
    _ = path.write_bytes(b"not really a wheel")
    return path


@pytest.fixture
def token_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """Publish with credentials available."""
    monkeypatch.setenv(TOKEN_ENV, FAKE_TOKEN)


@pytest.fixture
def token_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """Publish with no credentials, whatever the developer's shell holds."""
    monkeypatch.delenv(TOKEN_ENV, raising=False)


class FakeCompleted(NamedTuple):
    """Stands in for `subprocess.CompletedProcess`; only the status is read."""

    returncode: int


class TestPlanPublish:
    def test_builds_a_uv_publish_command(self, wheel: Path) -> None:
        plan = plan_publish([wheel])
        assert plan.argv[1] == "publish"
        assert plan.argv[0].endswith("uv")
        assert str(wheel.resolve()) in plan.argv

    @pytest.mark.usefixtures("token_set")
    def test_token_never_reaches_argv(self, wheel: Path) -> None:
        """The token goes through the environment so it cannot leak into `ps`."""
        plan = plan_publish([wheel])
        assert plan.needs_token is True
        assert not any(FAKE_TOKEN in arg for arg in plan.argv)
        assert not any("secret" in arg for arg in plan.argv)
        assert FAKE_TOKEN not in plan.display()

    def test_a_username_means_uv_authenticates_without_a_token(
        self, wheel: Path
    ) -> None:
        plan = plan_publish([wheel], username="krish")
        assert plan.needs_token is False

    def test_index_is_forwarded(self, wheel: Path) -> None:
        plan = plan_publish([wheel], index="testpypi")
        assert "--index" in plan.argv
        assert "testpypi" in plan.argv

    def test_publish_url_is_forwarded(self, wheel: Path) -> None:
        plan = plan_publish([wheel], publish_url="https://example.com/legacy/")
        assert "--publish-url" in plan.argv

    def test_index_and_publish_url_conflict(self, wheel: Path) -> None:
        with pytest.raises(PublishError, match="mutually exclusive"):
            _ = plan_publish([wheel], index="testpypi", publish_url="https://x/")

    def test_empty_file_list_is_rejected(self) -> None:
        with pytest.raises(PublishError, match="no distributions"):
            _ = plan_publish([])

    def test_missing_files_are_reported(self, tmp_path: Path) -> None:
        with pytest.raises(PublishError, match="do not exist"):
            _ = plan_publish([tmp_path / "absent.whl"])

    def test_display_is_printable(self, wheel: Path) -> None:
        assert "publish" in plan_publish([wheel]).display()


class TestResolveToken:
    """The token comes from the environment, and only from there."""

    @pytest.mark.usefixtures("token_set")
    def test_returns_the_exported_token(self) -> None:
        assert resolve_token() == FAKE_TOKEN

    def test_surrounding_whitespace_is_stripped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(TOKEN_ENV, f"  {FAKE_TOKEN}\n")
        assert resolve_token() == FAKE_TOKEN

    @pytest.mark.usefixtures("token_unset")
    def test_missing_token_explains_how_to_set_one(self) -> None:
        with pytest.raises(PublishError, match=TOKEN_ENV) as excinfo:
            _ = resolve_token()
        assert "export" in str(excinfo.value)

    def test_blank_token_counts_as_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(TOKEN_ENV, "   ")
        with pytest.raises(PublishError, match=TOKEN_ENV):
            _ = resolve_token()


class TestRunPublish:
    """uv is never reached without credentials."""

    @pytest.mark.usefixtures("token_unset")
    def test_missing_token_fails_before_uv_is_invoked(
        self, wheel: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fail(*_args, **_kwargs) -> Never:  # pragma: no cover - must not be reached
            raise AssertionError("uv publish was invoked without a token")

        monkeypatch.setattr("wheelforge.publish.subprocess.run", fail)
        with pytest.raises(PublishError, match=TOKEN_ENV):
            run_publish(plan_publish([wheel]))

    @pytest.mark.usefixtures("token_set")
    def test_a_token_is_not_added_to_the_command_line(
        self, wheel: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        argv_seen: list[str] = []
        kwargs_seen: dict[str, object] = {}

        def capture(argv: list[str], **kwargs: dict[str, object]) -> FakeCompleted:
            argv_seen.extend(argv)
            kwargs_seen.update(kwargs)
            return FakeCompleted(0)

        monkeypatch.setattr("wheelforge.publish.subprocess.run", capture)
        run_publish(plan_publish([wheel]))

        assert argv_seen  # the fake really was called
        assert not any(FAKE_TOKEN in arg for arg in argv_seen)
        # No explicit env: uv inherits this process's, token included.
        assert "env" not in kwargs_seen

    @pytest.mark.usefixtures("token_set")
    def test_a_failing_upload_is_reported(
        self, wheel: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "wheelforge.publish.subprocess.run",
            lambda argv, **_kwargs: FakeCompleted(1),  # ruff: ignore[unused-lambda-argument]  # pyrefly: ignore[implicit-any-lambda]
        )
        with pytest.raises(PublishError, match="not published"):
            run_publish(plan_publish([wheel]))
