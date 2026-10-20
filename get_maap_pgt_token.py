import json
import os
import sys

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry  # backoff_jitter requires urllib3>=2

TIMEOUT = (5, 30)  # (connect, read) seconds
MAX_RETRIES = 5  # i.e. up to 6 attempts
BACKOFF_FACTOR = 1.0  # sleeps ~ factor * 2**(n-1) seconds between retries, plus jitter
BACKOFF_JITTER = 1.0
BACKOFF_MAX = 30.0
RETRY_STATUSES = tuple(range(500, 600))
EXIT_CODE_PGT_FAILURE = 78  # distinct job exit status for PGT token failures


class PgtTokenError(Exception):
    """Raised when the MAAP PGT token cannot be obtained."""


def _session():
    """Session retrying connect errors, timeouts and 5xx with exponential backoff and jitter."""
    retry = Retry(
        total=MAX_RETRIES,
        backoff_factor=BACKOFF_FACTOR,
        backoff_jitter=BACKOFF_JITTER,
        backoff_max=BACKOFF_MAX,
        status_forcelist=RETRY_STATUSES,
        raise_on_status=False,  # hand back the last response so we can raise a clear error
    )
    session = requests.Session()
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def get_maap_pgt_token(username, maap_api_host=None):
    maap_api_host = maap_api_host or os.environ.get("MAAP_API_HOST")
    url = f"https://{maap_api_host}/api/members/{username}"
    headers = {"dps-token": os.environ.get("DPS_MACHINE_TOKEN")}

    try:
        with _session() as session:
            response = session.get(url, headers=headers, timeout=TIMEOUT)
    except requests.RequestException as e:
        raise PgtTokenError(
            f"Could not get MAAP_PGT for user '{username}' from {url} "
            f"after {MAX_RETRIES + 1} attempts; last error: {type(e).__name__}: {e}"
        ) from e

    if response.status_code >= 500:
        raise PgtTokenError(
            f"Could not get MAAP_PGT for user '{username}' from {url} "
            f"after {MAX_RETRIES + 1} attempts; last error: HTTP {response.status_code}"
        )

    try:
        response.raise_for_status()
    except requests.HTTPError as e:
        # 4xx is permanent (e.g. bad token, unknown user) and was not retried
        raise PgtTokenError(
            f"Request for user '{username}' to {url} failed: HTTP {response.status_code}"
        ) from e

    try:
        token = response.json()["session_key"]
    except (ValueError, KeyError, TypeError) as e:
        raise PgtTokenError(
            f"Response from {url} for user '{username}' has no usable 'session_key'"
        ) from e
    if not isinstance(token, str) or not token.strip():
        raise PgtTokenError(
            f"Response from {url} for user '{username}' has an empty 'session_key'"
        )
    return token


def report_failure(error, job_dir="."):
    """Surface the failure to HySDS.

    stderr lands in _stderr.txt; _alt_error.txt overrides the job's `error`
    field (job_worker reads it from the job dir). Keep it a short single line.
    """
    message = " ".join(str(error).split())
    print(f"Unable to get user MAAP_PGT token: {message}", file=sys.stderr)
    with open(os.path.join(job_dir, "_alt_error.txt"), "w") as f:
        f.write(f"MAAP_PGT token failure: {message}\n")


if __name__ == '__main__':
    with open("_job.json") as fr:
        job = json.loads(fr.read())
    username = job.get("username")
    try:
        if not username:
            # an empty MAAP_PGT would only surface later as a 401 in the user's code
            raise PgtTokenError("no 'username' in _job.json, cannot request a MAAP_PGT")
        print(get_maap_pgt_token(username))
    except PgtTokenError as e:
        # stdout is captured into MAAP_PGT by dps_wrapper.sh, so report on stderr
        report_failure(e)
        sys.exit(EXIT_CODE_PGT_FAILURE)
