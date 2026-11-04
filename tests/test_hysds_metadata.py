import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import hysds_metadata as hm
import process_outputs

ROOT = Path(__file__).parent.parent
JOB = {"username": "alice", "type": "job-my_algo:main", "tag": "t1"}


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("DEFAULT_OUTPUT_BUCKET", "maap-ops-workspace")
    monkeypatch.chdir(tmp_path)


def write_job(**extra):
    job = {**JOB, **extra}
    Path("_job.json").write_text(json.dumps(job))
    return job


def test_fields_present():
    write_job(output_bucket="org-bucket", output_prefix="org/team")
    info = hm.get_job_info()
    assert (info["output_bucket"], info["output_prefix"]) == ("org-bucket", "org/team")
    assert info["username"] == "alice" and info["algorithm_name"] == "my_algo"


def test_fields_missing_pre_api_job_uses_default_and_username():
    write_job()
    info = hm.get_job_info()
    assert (info["output_bucket"], info["output_prefix"]) == ("maap-ops-workspace", "alice")


@pytest.mark.parametrize("empty", ["", "   ", None])
def test_fields_empty_use_defaults(empty):
    write_job(output_bucket=empty, output_prefix=empty)
    info = hm.get_job_info()
    assert (info["output_bucket"], info["output_prefix"]) == ("maap-ops-workspace", "alice")


def test_bucket_without_prefix_defaults_prefix_to_username():
    write_job(output_bucket="org-bucket")
    info = hm.get_job_info()
    assert (info["output_bucket"], info["output_prefix"]) == ("org-bucket", "alice")


def test_job_bucket_does_not_need_env_default(monkeypatch):
    monkeypatch.delenv("DEFAULT_OUTPUT_BUCKET")
    write_job(output_bucket="org-bucket")
    assert hm.get_job_info()["output_bucket"] == "org-bucket"


@pytest.mark.parametrize("unset", [True, False])
def test_missing_env_default_fails_when_needed(monkeypatch, unset):
    if unset:
        monkeypatch.delenv("DEFAULT_OUTPUT_BUCKET")
    else:
        monkeypatch.setenv("DEFAULT_OUTPUT_BUCKET", " ")
    write_job()
    with pytest.raises(hm.OutputTargetError, match="DEFAULT_OUTPUT_BUCKET"):
        hm.get_job_info()


def test_unreadable_job_json_fails_loudly():
    with pytest.raises(hm.OutputTargetError, match="Could not read"):
        hm.get_job_info()
    Path("_job.json").write_text("{not json")
    with pytest.raises(hm.OutputTargetError, match="Could not read"):
        hm.get_job_info()


def test_missing_username_fails():
    Path("_job.json").write_text(json.dumps({"type": "job-a:b", "output_bucket": "bkt-1", "output_prefix": "p"}))
    with pytest.raises(hm.OutputTargetError, match="username"):
        hm.get_job_info()


@pytest.mark.parametrize("bucket", ["s3://bkt-1", "bkt/1", "UPPER", "ab", "a..b-c", "10.1.2.3", 5])
def test_invalid_bucket_rejected(bucket):
    write_job(output_bucket=bucket)
    with pytest.raises(hm.OutputTargetError, match="output_bucket"):
        hm.get_job_info()


@pytest.mark.parametrize("prefix", ["/a", "a/", "a//b", "a/../b", "./a", "a/./b", " a", 5])
def test_invalid_prefix_rejected(prefix):
    write_job(output_bucket="bkt-1", output_prefix=prefix)
    with pytest.raises(hm.OutputTargetError, match="output_prefix"):
        hm.get_job_info()


STAC = {
    "catalog_id": "c", "description": "d", "stac_version": "1.1.0", "item_count": 1,
    "items": [{"id": "i1", "collection": "col"}],
}


@pytest.mark.parametrize("stac", [None, STAC])
def test_met_json_contains_bucket_and_prefix(stac, tmp_path):
    write_job(output_bucket="org-bucket", output_prefix="org/team")
    out = tmp_path / "ds"
    out.mkdir()
    hm.write_metadata_files(str(out), "ds", stac, hm.get_job_info())
    met = json.loads((out / "ds.met.json").read_text())
    assert met["output_bucket"] == "org-bucket" and met["output_prefix"] == "org/team"
    assert ("stac_catalog" in met) == bool(stac)


@pytest.mark.parametrize("missing", ["output_bucket", "output_prefix"])
def test_create_met_metadata_refuses_empty_target(missing):
    write_job()
    info = hm.get_job_info()
    info[missing] = ""
    with pytest.raises(hm.OutputTargetError):
        hm.create_met_metadata("ds", info)


def test_per_item_met_contains_bucket_and_prefix(tmp_path):
    write_job(output_bucket="org-bucket", output_prefix="org/team")
    process_outputs.create_per_item_metadata(str(tmp_path), STAC, hm.get_job_info(), "ts")
    met = json.loads((tmp_path / "i1" / "i1.met.json").read_text())
    assert met["output_bucket"] == "org-bucket" and met["output_prefix"] == "org/team"


def test_create_hysds_metadata_propagates_errors(tmp_path):
    # no _job.json -> must raise rather than silently skipping .met.json
    with pytest.raises(hm.OutputTargetError):
        process_outputs.create_hysds_metadata(str(tmp_path), None)


def run_gate(tmp_path, env_extra):
    import os
    env = {k: v for k, v in os.environ.items() if k != "DEFAULT_OUTPUT_BUCKET"}
    env.update(env_extra)
    return subprocess.run([sys.executable, str(ROOT / "validate_output_target.py")],
                          cwd=tmp_path, env=env, capture_output=True, text=True)


def test_gate_ok(tmp_path):
    write_job()
    r = run_gate(tmp_path, {"DEFAULT_OUTPUT_BUCKET": "maap-ops-workspace"})
    assert r.returncode == 0 and "s3://maap-ops-workspace/alice/" in r.stdout


def test_gate_fails_without_job_or_default(tmp_path):
    r = run_gate(tmp_path, {})
    assert r.returncode == 1 and "FATAL" in r.stderr
    write_job()
    r = run_gate(tmp_path, {})
    assert r.returncode == 1 and "DEFAULT_OUTPUT_BUCKET" in r.stderr


def test_wrapper_gates_before_compute():
    text = (ROOT / "dps_wrapper.sh").read_text()
    assert text.index("validate_output_target.py") < text.index("cwltool ")
    assert text.index("validate_output_target.py") < text.index("aws s3 cp")
    assert "export DEFAULT_OUTPUT_BUCKET" in text
    # must not leak into the algorithm container
    assert "--preserve-environment DEFAULT_OUTPUT_BUCKET" not in text
