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
import argparse
from datetime import datetime
import hysds_metadata


def create_per_item_metadata(dataset_dir, stac_metadata, job_info, creation_timestamp):
    """
    Create HySDS metadata files for each STAC item

    Args:
        dataset_dir: Path to the dataset directory (the catalog root)
        stac_metadata: STAC metadata dict with items list
        job_info: Job metadata from _job.json
        creation_timestamp: ISO format timestamp string
    """
    if not stac_metadata or 'items' not in stac_metadata:
        return

    for item in stac_metadata['items']:
        item_id = item['id']
        item_dir = os.path.join(dataset_dir, item_id)

        # Ensure item directory exists
        os.makedirs(item_dir, exist_ok=True)

        # Create per-item .met.json (STAC data + job metadata + timestamp)
        item_met = {
            "username": job_info.get("username", "unknown"),
            "algorithm_name": job_info.get("algorithm_name", "unknown"),
            "algorithm_version": job_info.get("algorithm_version", "unknown"),
            "tag": job_info.get("tag", "unknown"),
            "creation_timestamp": creation_timestamp,
            "stac_item": item
        }

        met_path = os.path.join(item_dir, f"{item_id}.met.json")
        with open(met_path, 'w') as f:
            json.dump(item_met, f, indent=2)

        # Create per-item .dataset.json
        item_dataset = {
            "version": "v1.0",
            "dataset_type": item.get("collection", "unknown-collection"),
            "label": item.get("properties", {}).get("title", item_id)
        }

        dataset_path = os.path.join(item_dir, f"{item_id}.dataset.json")
        with open(dataset_path, 'w') as f:
            json.dump(item_dataset, f, indent=2)

        print(f"  Created per-item metadata: {item_id}")


def process_outputs(stage_out_result_file, create_item_metadata=False):
    """
    Process all CWL outputs from stage_out.py

    Args:
        stage_out_result_file: Path to JSON file from stage_out.py
        create_item_metadata: Whether to create per-item metadata files (default: False)
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
        return process_single_output(primary_output, create_item_metadata)

    print(f"\nProcessing {len(outputs)} CWL output(s)")

    # Build a set of directories already being processed
    output_dirs = {os.path.abspath(output['output_dir']) for output in outputs if output.get('is_directory')}

    # Process each output as a separate dataset
    created_datasets = []
    for output_info in outputs:
        output_path = os.path.abspath(output_info.get('output_dir'))

        # Handle File outputs
        if not output_info.get('is_directory'):
            parent_dir = os.path.dirname(output_path)

            # If parent directory is not already being processed, create dataset for it
            if parent_dir and parent_dir not in output_dirs:
                print(f"File output detected, creating dataset for parent directory: {parent_dir}")
                file_output_info = {
                    'output_id': output_info.get('output_id'),
                    'output_dir': parent_dir,
                    'output_type': 'Directory',
                    'is_directory': True
                }
                try:
                    dataset_name = process_single_output_with_metadata(file_output_info, create_item_metadata)
                    if dataset_name:
                        created_datasets.append(dataset_name)
                except Exception as e:
                    print(f"Error processing parent directory for file output {output_info.get('output_id')}: {e}")
            continue

        # Process Directory outputs
        try:
            dataset_name = process_single_output_with_metadata(output_info, create_item_metadata)
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


def process_single_output(primary_output, create_item_metadata=False):
    """
    Fallback: process single output directory (backward compatibility)

    Args:
        primary_output: Path to output directory
        create_item_metadata: Whether to create per-item metadata files (default: False)
    """
    if not primary_output or not os.path.exists(primary_output):
        print("No output directory found")
        return False

    # Generate creation timestamp (ISO format with Z suffix)
    creation_timestamp = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.%fZ')

    # Use original directory name (do NOT rename)
    dataset_name = os.path.basename(primary_output)

    print(f"Processing output directory: {primary_output}")
    print(f"  Created: {creation_timestamp}")

    # Copy logs
    copy_logs(primary_output)

    # Create HySDS metadata (without STAC)
    create_hysds_metadata(primary_output, None, creation_timestamp)

    return True


def process_single_output_with_metadata(output_info, create_item_metadata=False):
    """
    Process a single CWL output with optional STAC metadata

    Args:
        output_info: Dictionary with output_id, output_dir, and optional stac_metadata
        create_item_metadata: Whether to create per-item metadata files (default: False)

    Returns:
        Dataset name if successful, None otherwise
    """
    output_id = output_info.get('output_id')
    output_dir = output_info.get('output_dir')
    stac_metadata = output_info.get('stac_metadata')

    if not output_dir or not os.path.exists(output_dir):
        print(f"Output directory not found: {output_dir}")
        return None

    # Generate creation timestamp (ISO format with Z suffix)
    creation_timestamp = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.%fZ')

    # Use original directory name (do NOT rename)
    dataset_name = os.path.basename(output_dir)

    print(f"\nProcessing output: {output_id}")
    print(f"  Directory: {output_dir}")
    print(f"  Created: {creation_timestamp}")

    if stac_metadata:
        print(f"  STAC Catalog: {stac_metadata.get('catalog_id')}")
        print(f"  Items: {stac_metadata.get('item_count', 0)}")

    # Copy logs to output directory
    copy_logs(output_dir)

    # Create HySDS metadata (per-output) with timestamp
    create_hysds_metadata(output_dir, stac_metadata, creation_timestamp)

    # Create per-item metadata if STAC and flag is enabled
    if stac_metadata and create_item_metadata:
        job_info = hysds_metadata.get_job_info()
        create_per_item_metadata(output_dir, stac_metadata, job_info, creation_timestamp)

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


def create_hysds_metadata(dataset_dir, stac_metadata, creation_timestamp=None):
    """
    Create HySDS metadata files

    Args:
        dataset_dir: Path to dataset directory
        stac_metadata: STAC metadata dict or None
        creation_timestamp: ISO format timestamp (optional)
    """
    try:
        job_info = hysds_metadata.get_job_info()
        hysds_metadata.write_metadata_files(
            dataset_dir=dataset_dir,
            dataset_name=os.path.basename(dataset_dir),
            stac_metadata=stac_metadata,
            job_info=job_info,
            creation_timestamp=creation_timestamp
        )
    except Exception as e:
        print(f"  Error creating HySDS metadata: {e}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Process CWL outputs and create HySDS datasets'
    )
    parser.add_argument(
        'stage_out_result_file',
        help='Path to JSON file from stage_out.py'
    )
    parser.add_argument(
        '--create-item-metadata',
        action='store_true',
        default=False,
        help='Create per-item metadata files for STAC items (default: False)'
    )

    args = parser.parse_args()
    success = process_outputs(args.stage_out_result_file, args.create_item_metadata)
    sys.exit(0 if success else 1)
