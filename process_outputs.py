#!/usr/bin/env python
"""
Process CWL outputs and create HySDS datasets

This script reads the output from stage_out.py and creates separate HySDS datasets
for each CWL output, handling both STAC and non-STAC outputs.
"""

import sys
import json
import os
import shutil
from datetime import datetime
import hysds_metadata


def get_job_info():
    """Extract job information from _job.json"""
    try:
        with open("_job.json") as fr:
            job = json.loads(fr.read())
            username = job.get("username", "null")
            job_type_info = str(job.get("type")).split(":")  # example job-s1_orbit_crawler:release-20190313
            algo_name = job_type_info[0].replace("job-", "")
            algo_version = job_type_info[1]
            tag = job.get("tag", "null-tag")
            return {"username": username, "algorithm_name": algo_name, "algorithm_version": algo_version, "tag": tag}
    except Exception as e:
        print(f"Warning: Could not read _job.json: {e}")
        return {"username": "unknown", "algorithm_name": "unknown", "algorithm_version": "unknown", "tag": "unknown"}


def process_outputs(stage_out_result_file):
    """
    Process all CWL outputs from stage_out.py

    Args:
        stage_out_result_file: Path to JSON file from stage_out.py
    """
    try:
        # Read stage_out result
        with open(stage_out_result_file) as f:
            stage_out_result = json.load(f)
    except Exception as e:
        print(f"Error reading stage_out result: {e}")
        return False

    outputs = stage_out_result.get('outputs', [])
    primary_output = stage_out_result.get('primary_output')

    # If no outputs discovered, fall back to single-output behavior
    if not outputs or not primary_output:
        print("No outputs discovered, using fallback behavior")
        return process_single_output(primary_output)

    print(f"\nProcessing {len(outputs)} CWL output(s)")

    # Process each output as a separate dataset
    created_datasets = []
    for output_info in outputs:
        try:
            dataset_name = process_single_output_with_metadata(output_info)
            if dataset_name:
                created_datasets.append(dataset_name)
        except Exception as e:
            print(f"Error processing output {output_info.get('output_id')}: {e}")
            continue

    if created_datasets:
        print(f"\n=== Created {len(created_datasets)} Dataset(s) ===")
        for dataset_name in created_datasets:
            print(f"  - {dataset_name}")
        return True
    else:
        print("No datasets created")
        return False


def process_single_output(primary_output):
    """
    Fallback: process single output directory (backward compatibility)

    Args:
        primary_output: Path to output directory
    """
    if not primary_output or not os.path.exists(primary_output):
        print("No output directory found")
        return False

    # Create timestamped dataset name
    timestamp = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.%f')
    dataset_name = f"output-{timestamp}"

    # Copy logs
    copy_logs(primary_output)

    # Rename to dataset name
    if os.path.exists(dataset_name):
        shutil.rmtree(dataset_name)
    os.rename(primary_output, dataset_name)
    print(f"Renamed {primary_output} -> {dataset_name}")

    # Create HySDS metadata (without STAC)
    create_hysds_metadata(dataset_name, None)

    return True


def process_single_output_with_metadata(output_info):
    """
    Process a single CWL output with optional STAC metadata

    Args:
        output_info: Dictionary with output_id, output_dir, and optional stac_metadata

    Returns:
        Dataset name if successful, None otherwise
    """
    output_id = output_info.get('output_id')
    output_dir = output_info.get('output_dir')
    stac_metadata = output_info.get('stac_metadata')

    if not output_dir or not os.path.exists(output_dir):
        print(f"Output directory not found: {output_dir}")
        return None

    # Create timestamped dataset name from output_id
    timestamp = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.%f')
    dataset_name = f"{output_id}-{timestamp}"

    print(f"\nProcessing output: {output_id}")
    print(f"  Source: {output_dir}")
    print(f"  Dataset: {dataset_name}")

    if stac_metadata:
        print(f"  STAC Catalog: {stac_metadata.get('catalog_id')}")
        print(f"  Items: {stac_metadata.get('item_count', 0)}")

    # Copy logs to output directory
    copy_logs(output_dir)

    # Save STAC metadata if available (as reference in dataset)
    if stac_metadata:
        metadata_file = os.path.join(output_dir, ".stac_metadata.json")
        try:
            with open(metadata_file, 'w') as f:
                json.dump(stac_metadata, f, indent=2)
            print(f"  Saved STAC metadata: {metadata_file}")
        except Exception as e:
            print(f"  Warning: Could not save STAC metadata: {e}")

    # Rename to dataset name
    if os.path.exists(dataset_name):
        print(f"  Removing existing dataset: {dataset_name}")
        shutil.rmtree(dataset_name)

    os.rename(output_dir, dataset_name)
    print(f"  Renamed: {output_dir} -> {dataset_name}")

    # Create HySDS metadata
    create_hysds_metadata(dataset_name, stac_metadata)

    return dataset_name


def copy_logs(output_dir):
    """
    Copy standard output/error logs to output directory

    Args:
        output_dir: Path to output directory
    """
    try:
        log_files = ['_stdout.txt', '_stderr.txt']
        for log_file in log_files:
            if os.path.exists(log_file):
                dest_path = os.path.join(output_dir, log_file)
                shutil.copy2(log_file, dest_path)
                print(f"  Copied: {log_file}")
    except Exception as e:
        print(f"  Warning: Could not copy logs: {e}")


def create_hysds_metadata(dataset_dir, stac_metadata):
    """
    Create HySDS metadata files

    Args:
        dataset_dir: Path to dataset directory
        stac_metadata: STAC metadata dict or None
    """
    try:
        job_info = get_job_info()
        hysds_metadata.write_metadata_files(
            dataset_dir=dataset_dir,
            dataset_name=os.path.basename(dataset_dir),
            stac_metadata=stac_metadata,
            job_info=job_info
        )
    except Exception as e:
        print(f"  Error creating HySDS metadata: {e}")


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: process_outputs.py <stage_out_result_file>")
        sys.exit(1)

    result_file = sys.argv[1]
    success = process_outputs(result_file)
    sys.exit(0 if success else 1)
