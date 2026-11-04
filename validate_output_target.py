"""
Pre-compute gate: resolve and validate the job's output bucket/prefix.

Run from dps_wrapper.sh before any expensive work so that a job which cannot be
published (missing/unreadable _job.json, no default bucket in /maap-dps.env,
malformed bucket or prefix) fails immediately instead of after the CWL run.
Local checks only: no network access, no bucket probing.
"""
import sys

import hysds_metadata


def main() -> int:
    try:
        # Same call the publish-time metadata step makes, so the gate cannot diverge from it.
        job_info = hysds_metadata.get_job_info()
    except hysds_metadata.OutputTargetError as e:
        print(f"FATAL: {e}", file=sys.stderr)
        return 1
    print(f"Output target: s3://{job_info['output_bucket']}/{job_info['output_prefix']}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
