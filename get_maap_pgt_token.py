import json
import os
import random
import sys
import time

import requests

TIMEOUT = (5, 30)  # (connect, read) seconds
MAX_ATTEMPTS = 6
BACKOFF_BASE = 1.0  # seconds; doubles each attempt
BACKOFF_CAP = 30.0
EXIT_CODE_PGT_FAILURE = 78  # distinct job exit status for PGT token failures


class PgtTokenError(Exception):
    """Raised when the MAAP PGT token cannot be obtained."""


def _sleep_time(attempt):
    """Exponential backoff with full jitter for the given 0-based attempt."""
    return random.uniform(0, min(BACKOFF_CAP, BACKOFF_BASE * 2 ** attempt))


def get_maap_pgt_token(username, maap_api_host=None):
    maap_api_host = maap_api_host or os.environ.get("MAAP_API_HOST")
    url = f"https://{maap_api_host}/api/members/{username}"
    headers = {"dps-token": os.environ.get("DPS_MACHINE_TOKEN")}

    last_error = None
    for attempt in range(MAX_ATTEMPTS):
        if attempt:
            time.sleep(_sleep_time(attempt - 1))
        try:
            response = requests.get(url, headers=headers, timeout=TIMEOUT)
        except (requests.ConnectionError, requests.Timeout) as e:
            last_error = f"{type(e).__name__}: {e}"
            continue

        if response.status_code >= 500:
            last_error = f"HTTP {response.status_code}"
            continue

        try:
            response.raise_for_status()
        except requests.HTTPError as e:
            # 4xx is permanent (e.g. bad token, unknown user): do not retry
            raise PgtTokenError(
                f"Request for user '{username}' to {url} failed: HTTP {response.status_code}"
            ) from e

        try:
            return response.json()["session_key"]
        except (ValueError, KeyError, TypeError) as e:
            raise PgtTokenError(
                f"Response from {url} for user '{username}' has no usable 'session_key'"
            ) from e

    raise PgtTokenError(
        f"Could not get MAAP_PGT for user '{username}' from {url} "
        f"after {MAX_ATTEMPTS} attempts; last error: {last_error}"
    )


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
        if username:
            try:
                maap_pgt_token = get_maap_pgt_token(username)
                print(maap_pgt_token)
            except PgtTokenError as e:
                # stdout is captured into MAAP_PGT by dps_wrapper.sh, so report on stderr
                report_failure(e)
                sys.exit(EXIT_CODE_PGT_FAILURE)
