import sys
import json
import os
import hysds_metadata


def get_info_from_job():
    """Extract job information from _job.json"""
    with open("_job.json") as fr:
        job = json.loads(fr.read())
        username = job.get("username", "null")
        job_type_info = str(job.get("type")).split(":")  # example job-s1_orbit_crawler:release-20190313
        algo_name = job_type_info[0].replace("job-", "")
        algo_version = job_type_info[1]
        tag = job.get("tag", "null-tag")
        return {"username": username, "algorithm_name": algo_name, "algorithm_version": algo_version, "tag": tag}


def load_stac_metadata(dataset_dir):
    """
    Load STAC metadata if available

    Args:
        dataset_dir: Path to the dataset directory

    Returns:
        STAC metadata dict or None if not available
    """
    metadata_file = os.path.join(dataset_dir, ".stac_metadata.json")
    if os.path.exists(metadata_file):
        try:
            with open(metadata_file) as f:
                return json.load(f)
        except Exception as e:
            print(f"Warning: Could not load STAC metadata: {e}")
    return None


if __name__ == '__main__':
    dataset_name = sys.argv[1]

    # Get job metadata
    job_info = get_info_from_job()

    # Try to load STAC metadata if available
    stac_metadata = load_stac_metadata(dataset_name)

    # Create HySDS metadata files
    hysds_metadata.write_metadata_files(
        dataset_dir=dataset_name,
        dataset_name=dataset_name,
        stac_metadata=stac_metadata,
        job_info=job_info
    )

