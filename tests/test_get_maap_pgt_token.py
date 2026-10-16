import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

sys.path.insert(0, str(Path(__file__).parent.parent))

import get_maap_pgt_token as mod
from get_maap_pgt_token import get_maap_pgt_token, PgtTokenError


def _resp(status=200, body=None):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = body if body is not None else {}
    if status >= 400:
        r.raise_for_status.side_effect = requests.HTTPError(f"{status}")
    return r


def _mock_session(get):
    """Patch mod._session to return a context-manager session whose .get is `get`."""
    session = MagicMock()
    session.__enter__.return_value = session
    session.get = get
    return patch.object(mod, "_session", return_value=session)


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("MAAP_API_HOST", "api.example.org")
    monkeypatch.setenv("DPS_MACHINE_TOKEN", "tok")


@pytest.fixture
def fast_backoff(monkeypatch):
    monkeypatch.setattr(mod, "BACKOFF_FACTOR", 0.01)
    monkeypatch.setattr(mod, "BACKOFF_JITTER", 0.01)


@pytest.fixture
def flaky_server():
    """Local HTTP server; set .statuses to the sequence of codes to return, then 200."""
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.server.hits += 1
            code = self.server.statuses.pop(0) if self.server.statuses else 200
            body = json.dumps({"session_key": "abc"} if code == 200 else {}).encode()
            self.send_response(code)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    server.hits, server.statuses = 0, []
    threading.Thread(target=server.serve_forever, daemon=True).start()
    server.url = f"http://127.0.0.1:{server.server_port}/"
    yield server
    server.shutdown()


# --- retry behaviour, against a real server through the real session ---

def test_session_retries_5xx_then_succeeds(flaky_server, fast_backoff):
    flaky_server.statuses = [503, 502]
    with mod._session() as s:
        r = s.get(flaky_server.url, timeout=mod.TIMEOUT)
    assert r.status_code == 200
    assert flaky_server.hits == 3


def test_session_gives_up_after_max_retries_returning_last_response(flaky_server, fast_backoff):
    flaky_server.statuses = [500] * 20
    with mod._session() as s:
        r = s.get(flaky_server.url, timeout=mod.TIMEOUT)
    assert r.status_code == 500
    assert flaky_server.hits == mod.MAX_RETRIES + 1


def test_session_does_not_retry_4xx(flaky_server, fast_backoff):
    flaky_server.statuses = [401, 200]
    with mod._session() as s:
        r = s.get(flaky_server.url, timeout=mod.TIMEOUT)
    assert r.status_code == 401
    assert flaky_server.hits == 1


def test_session_retries_connection_errors(fast_backoff):
    with mod._session() as s:
        with pytest.raises(requests.ConnectionError):
            s.get("http://127.0.0.1:9/", timeout=mod.TIMEOUT)


# --- get_maap_pgt_token logic ---

def test_success_passes_timeout_and_header():
    get = MagicMock(return_value=_resp(200, {"session_key": "abc"}))
    with _mock_session(get):
        assert get_maap_pgt_token("alice") == "abc"
    get.assert_called_once_with(
        "https://api.example.org/api/members/alice",
        headers={"dps-token": "tok"},
        timeout=mod.TIMEOUT,
    )


def test_exhausted_5xx_gives_clear_error():
    with _mock_session(MagicMock(return_value=_resp(503))):
        with pytest.raises(PgtTokenError, match=r"after 6 attempts.*HTTP 503"):
            get_maap_pgt_token("alice")


def test_exhausted_connection_errors_give_clear_error():
    with _mock_session(MagicMock(side_effect=requests.ConnectionError("boom"))):
        with pytest.raises(PgtTokenError, match=r"after 6 attempts.*ConnectionError: boom"):
            get_maap_pgt_token("alice")


def test_4xx_gives_clear_error():
    with _mock_session(MagicMock(return_value=_resp(401))):
        with pytest.raises(PgtTokenError, match="HTTP 401"):
            get_maap_pgt_token("alice")


def test_missing_session_key_gives_clear_error():
    with _mock_session(MagicMock(return_value=_resp(200, {"other": 1}))):
        with pytest.raises(PgtTokenError, match="session_key"):
            get_maap_pgt_token("alice")


def test_non_json_body_gives_clear_error():
    r = _resp(200)
    r.json.side_effect = ValueError("not json")
    with _mock_session(MagicMock(return_value=r)):
        with pytest.raises(PgtTokenError, match="session_key"):
            get_maap_pgt_token("alice")


# --- failure reporting to HySDS ---

def test_report_failure_writes_stderr_and_alt_error(tmp_path, capsys):
    mod.report_failure(PgtTokenError("HTTP 503\nafter 6 attempts"), job_dir=str(tmp_path))
    assert "HTTP 503 after 6 attempts" in capsys.readouterr().err
    assert (tmp_path / "_alt_error.txt").read_text() == "MAAP_PGT token failure: HTTP 503 after 6 attempts\n"


def test_main_exits_with_custom_code_and_keeps_stdout_clean(tmp_path):
    (tmp_path / "_job.json").write_text(json.dumps({"username": "alice"}))
    # nothing listens on localhost:9; sleep is stubbed so retries are exhausted quickly
    code = (
        "import runpy, time; time.sleep = lambda s: None; "
        f"runpy.run_path({mod.__file__!r}, run_name='__main__')"
    )
    r = subprocess.run(
        [sys.executable, "-c", code], cwd=tmp_path, capture_output=True, text=True,
        env={"MAAP_API_HOST": "localhost:9", "DPS_MACHINE_TOKEN": "t", "PATH": "",
             "PYTHONPATH": str(Path(mod.__file__).parent)},
    )
    assert r.returncode == mod.EXIT_CODE_PGT_FAILURE, r.stderr
    assert r.stdout == ""
    assert "Unable to get user MAAP_PGT token" in r.stderr
    assert (tmp_path / "_alt_error.txt").exists()
