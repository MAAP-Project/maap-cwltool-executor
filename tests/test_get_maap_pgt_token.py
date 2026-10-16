import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
import requests

sys.path.insert(0, str(Path(__file__).parent.parent))

import get_maap_pgt_token as mod
from get_maap_pgt_token import get_maap_pgt_token, PgtTokenError


def _resp(status=200, body=None):
    r = Mock()
    r.status_code = status
    r.json.return_value = body if body is not None else {}
    if status >= 400:
        r.raise_for_status.side_effect = requests.HTTPError(f"{status}")
    return r


@pytest.fixture(autouse=True)
def no_sleep():
    with patch.object(mod.time, "sleep") as s:
        yield s


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("MAAP_API_HOST", "api.example.org")
    monkeypatch.setenv("DPS_MACHINE_TOKEN", "tok")


def test_success_passes_timeout_and_header():
    with patch.object(mod.requests, "get", return_value=_resp(200, {"session_key": "abc"})) as g:
        assert get_maap_pgt_token("alice") == "abc"
    g.assert_called_once_with(
        "https://api.example.org/api/members/alice",
        headers={"dps-token": "tok"},
        timeout=mod.TIMEOUT,
    )


def test_retries_flaky_endpoint_then_succeeds(no_sleep):
    side = [
        requests.ConnectionError("boom"),
        _resp(503),
        _resp(200, {"session_key": "abc"}),
    ]
    with patch.object(mod.requests, "get", side_effect=side) as g:
        assert get_maap_pgt_token("alice") == "abc"
    assert g.call_count == 3
    assert no_sleep.call_count == 2


def test_retries_on_timeout():
    side = [requests.Timeout("slow"), _resp(200, {"session_key": "abc"})]
    with patch.object(mod.requests, "get", side_effect=side):
        assert get_maap_pgt_token("alice") == "abc"


def test_permanent_5xx_gives_clear_error_after_max_attempts():
    with patch.object(mod.requests, "get", return_value=_resp(500)) as g:
        with pytest.raises(PgtTokenError, match=r"after 6 attempts.*HTTP 500"):
            get_maap_pgt_token("alice")
    assert g.call_count == mod.MAX_ATTEMPTS


def test_4xx_is_not_retried():
    with patch.object(mod.requests, "get", return_value=_resp(401)) as g:
        with pytest.raises(PgtTokenError, match="HTTP 401"):
            get_maap_pgt_token("alice")
    assert g.call_count == 1


def test_missing_session_key_gives_clear_error():
    with patch.object(mod.requests, "get", return_value=_resp(200, {"other": 1})):
        with pytest.raises(PgtTokenError, match="session_key"):
            get_maap_pgt_token("alice")


def test_non_json_body_gives_clear_error():
    r = _resp(200)
    r.json.side_effect = ValueError("not json")
    with patch.object(mod.requests, "get", return_value=r):
        with pytest.raises(PgtTokenError, match="session_key"):
            get_maap_pgt_token("alice")


def test_backoff_is_bounded_and_grows():
    for attempt in range(10):
        assert 0 <= mod._sleep_time(attempt) <= min(mod.BACKOFF_CAP, mod.BACKOFF_BASE * 2 ** attempt)


def test_report_failure_writes_stderr_and_alt_error(tmp_path, capsys):
    mod.report_failure(PgtTokenError("HTTP 503\nafter 6 attempts"), job_dir=str(tmp_path))
    assert "HTTP 503 after 6 attempts" in capsys.readouterr().err
    assert (tmp_path / "_alt_error.txt").read_text() == "MAAP_PGT token failure: HTTP 503 after 6 attempts\n"


def test_main_exits_with_custom_code_and_keeps_stdout_clean(tmp_path, monkeypatch):
    import subprocess, json
    (tmp_path / "_job.json").write_text(json.dumps({"username": "alice"}))
    # port 9 on localhost refuses connections: retries are exhausted quickly with backoff patched out
    code = (
        "import sys, runpy, time; time.sleep = lambda s: None; "
        f"runpy.run_path({mod.__file__!r}, run_name='__main__')"
    )
    r = subprocess.run(
        [sys.executable, "-c", code], cwd=tmp_path, capture_output=True, text=True,
        env={"MAAP_API_HOST": "localhost:9", "DPS_MACHINE_TOKEN": "t", "PATH": ""},
    )
    assert r.returncode == mod.EXIT_CODE_PGT_FAILURE
    assert r.stdout == ""
    assert "Unable to get user MAAP_PGT token" in r.stderr
    assert (tmp_path / "_alt_error.txt").exists()
