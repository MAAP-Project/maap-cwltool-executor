import sys
import json
import os
import hysds_metadata


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
    job_info = hysds_metadata.get_job_info()

    # Try to load STAC metadata if available
    stac_metadata = load_stac_metadata(dataset_name)

    # Create HySDS metadata files
    hysds_metadata.write_metadata_files(
        dataset_dir=dataset_name,
        dataset_name=dataset_name,
        stac_metadata=stac_metadata,
        job_info=job_info
    )

