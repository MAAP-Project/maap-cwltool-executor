"""
HySDS Metadata Creation Module

This module handles creation of HySDS-compliant metadata files (.dataset.json and .met.json)
for both STAC catalog outputs and non-STAC directory outputs.
"""

import json
import os
import re
from typing import Dict, Any, Optional, Tuple

DEFAULT_OUTPUT_BUCKET_ENV = "DEFAULT_OUTPUT_BUCKET"

# S3 bucket naming rules (3-63 chars, lowercase letters/digits/dots/hyphens).
_BUCKET_RE = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
_IPV4_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")


class OutputTargetError(RuntimeError):
    """Raised when the job's output bucket/prefix cannot be resolved or is invalid."""


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def validate_output_bucket(bucket: Any) -> str:
    """Return the bucket name if it is a valid bare S3 bucket name, else raise."""
    if not isinstance(bucket, str) or not _BUCKET_RE.match(bucket) \
            or ".." in bucket or _IPV4_RE.match(bucket):
        raise OutputTargetError(
            f"Invalid output_bucket {bucket!r}: expected a bare S3 bucket name "
            "(no s3:// scheme, no slashes)"
        )
    return bucket


def validate_output_prefix(prefix: Any) -> str:
    """Return the prefix if it is already normalized, else raise.

    The API owns normalization; the executor only refuses values that would
    produce a broken or unsafe publish location.
    """
    if not isinstance(prefix, str) or not prefix:
        raise OutputTargetError(f"Invalid output_prefix {prefix!r}: must be a non-empty string")
    if prefix != prefix.strip() or any(ord(c) < 32 for c in prefix):
        raise OutputTargetError(f"Invalid output_prefix {prefix!r}: whitespace or control characters")
    if prefix.startswith("/") or prefix.endswith("/"):
        raise OutputTargetError(f"Invalid output_prefix {prefix!r}: leading or trailing slash")
    for segment in prefix.split("/"):
        if segment in ("", ".", ".."):
            raise OutputTargetError(
                f"Invalid output_prefix {prefix!r}: empty, '.' or '..' path segment"
            )
    return prefix


def load_job(path: str = "_job.json") -> Dict[str, Any]:
    """Read _job.json. Fails loudly: there is no safe fallback without it."""
    try:
        with open(path) as fr:
            job = json.load(fr)
    except Exception as e:
        raise OutputTargetError(f"Could not read {path}: {e}") from e
    if not isinstance(job, dict):
        raise OutputTargetError(f"{path} is not a JSON object")
    return job


def resolve_output_target(job: Dict[str, Any]) -> Tuple[str, str]:
    """
    Resolve (output_bucket, output_prefix) for a job.

    - bucket: job["output_bucket"], else $DEFAULT_OUTPUT_BUCKET (from maap-dps.env)
    - prefix: job["output_prefix"], else the job's username
    Jobs submitted before the API sent these fields therefore keep working.
    Raises OutputTargetError if a value is missing or invalid; never guesses.
    """
    bucket = job.get("output_bucket")
    if _is_blank(bucket):
        bucket = os.environ.get(DEFAULT_OUTPUT_BUCKET_ENV)
        if _is_blank(bucket):
            raise OutputTargetError(
                f"No output_bucket in _job.json and {DEFAULT_OUTPUT_BUCKET_ENV} is not set "
                "(expected from /maap-dps.env)"
            )
    prefix = job.get("output_prefix")
    if _is_blank(prefix):
        prefix = job.get("username")
        if _is_blank(prefix):
            raise OutputTargetError("No output_prefix and no username in _job.json")
    return validate_output_bucket(bucket), validate_output_prefix(prefix)


def get_job_info():
    """Extract job information from _job.json. Raises OutputTargetError on failure."""
    job = load_job()
    output_bucket, output_prefix = resolve_output_target(job)
    username = job.get("username")
    if _is_blank(username):
        raise OutputTargetError("No username in _job.json")
    job_type_info = str(job.get("type")).split(":")  # example job-s1_orbit_crawler:release-20190313
    algo_name = job_type_info[0].replace("job-", "")
    algo_version = job_type_info[1] if len(job_type_info) > 1 else "unknown"
    tag = job.get("tag", "null-tag")
    return {
        "username": username,
        "algorithm_name": algo_name,
        "algorithm_version": algo_version,
        "tag": tag,
        "output_bucket": output_bucket,
        "output_prefix": output_prefix,
    }


def create_dataset_metadata(
    dataset_name: str,
    job_info: Dict[str, Any],
    stac_metadata: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Create HySDS dataset.json metadata

    Args:
        dataset_name: Name of the HySDS dataset
        job_info: Job metadata (username, algorithm_name, version, tag)
        stac_metadata: STAC catalog metadata (optional)

    Returns:
        Dictionary for dataset.json file
    """
    dataset_json = {
        "version": "v1.0"
    }

    # If STAC metadata present, add STAC-specific fields
    if stac_metadata:
        dataset_json["stac_enabled"] = True
        dataset_json["stac_catalog_id"] = stac_metadata.get('catalog_id')

        # Extract collection IDs from items
        collections = set()
        for item in stac_metadata.get('items', []):
            if item.get('collection'):
                collections.add(item['collection'])

        dataset_json["stac_collections"] = list(collections)
        dataset_json["total_items"] = stac_metadata.get('item_count', 0)
        dataset_json["output_type"] = "stac_catalog"

    return dataset_json


def create_met_metadata(
    dataset_name: str,
    job_info: Dict[str, Any],
    stac_metadata: Optional[Dict[str, Any]] = None,
    creation_timestamp: Optional[str] = None
) -> Dict[str, Any]:
    """
    Create HySDS met.json metadata

    Args:
        dataset_name: Name of the HySDS dataset
        job_info: Job metadata (username, algorithm_name, version, tag)
        stac_metadata: STAC catalog metadata (optional), must contain:
            - catalog_id: Catalog identifier
            - description: Catalog description
            - stac_version: STAC specification version
            - items: List of STAC items with full metadata (id, collection, datetime, bbox, assets, properties)
        creation_timestamp: ISO format timestamp (optional, generated if not provided)

    Returns:
        Dictionary for met.json file. When stac_metadata is provided, includes:
        - Basic job metadata (username, algorithm_name, algorithm_version, tag, output_bucket,
          output_prefix, creation_timestamp)
        - stac_catalog: Catalog summary with collections array grouped by collection ID,
          including complete item inventory for search and discovery
    """
    from datetime import datetime, timezone

    # Generate timestamp if not provided
    if not creation_timestamp:
        creation_timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')

    met_json = {
        "username": job_info.get("username", "unknown"),
        "algorithm_name": job_info.get("algorithm_name", "unknown"),
        "algorithm_version": job_info.get("algorithm_version", "unknown"),
        "tag": job_info.get("tag", "unknown"),
        "output_bucket": validate_output_bucket(job_info.get("output_bucket")),
        "output_prefix": validate_output_prefix(job_info.get("output_prefix")),
        "creation_timestamp": creation_timestamp
    }

    # If STAC metadata present, add STAC catalog metadata with items organized by collection
    if stac_metadata:
        # Extract items list
        items = stac_metadata.get('items', [])

        # Group items by collection ID
        collections_dict = {}
        uncategorized_items = []

        for item in items:
            collection_id = item.get('collection')

            if collection_id is None or collection_id == '':
                # Handle items without collection
                uncategorized_items.append(item)
            else:
                # Group by collection ID
                if collection_id not in collections_dict:
                    collections_dict[collection_id] = []
                collections_dict[collection_id].append(item)

        # Build collections array
        collections = []

        # Add regular collections (sorted alphabetically)
        for collection_id in sorted(collections_dict.keys()):
            collection_items = collections_dict[collection_id]
            collections.append({
                "id": collection_id,
                "item_count": len(collection_items),
                "items": collection_items
            })

        # Add uncategorized collection at the end if present
        if uncategorized_items:
            collections.append({
                "id": "uncategorized",
                "item_count": len(uncategorized_items),
                "items": uncategorized_items
            })

        # Build STAC catalog summary with collections
        stac_catalog_summary = {
            "id": stac_metadata.get('catalog_id'),
            "description": stac_metadata.get('description'),
            "stac_version": stac_metadata.get('stac_version'),
            "collections": collections
        }

        met_json["stac_catalog"] = stac_catalog_summary

    return met_json


def write_metadata_files(
    dataset_dir: str,
    dataset_name: str,
    stac_metadata: Optional[Dict[str, Any]],
    job_info: Dict[str, Any],
    creation_timestamp: Optional[str] = None
) -> None:
    """
    Main function to write all HySDS metadata files

    Args:
        dataset_dir: Path to the dataset directory
        dataset_name: Name of the dataset (used for file naming)
        stac_metadata: STAC metadata if available
        job_info: Job metadata from _job.json
        creation_timestamp: ISO format timestamp (optional, generated if not provided)
    """
    try:
        # Create dataset.json
        dataset_json = create_dataset_metadata(dataset_name, job_info, stac_metadata)
        dataset_json_path = os.path.join(dataset_dir, f"{dataset_name}.dataset.json")

        with open(dataset_json_path, 'w') as f:
            json.dump(dataset_json, f, indent=2)

        print(f"Created: {dataset_json_path}")

        # Create met.json
        met_json = create_met_metadata(dataset_name, job_info, stac_metadata, creation_timestamp)
        met_json_path = os.path.join(dataset_dir, f"{dataset_name}.met.json")

        with open(met_json_path, 'w') as f:
            json.dump(met_json, f, indent=2)

        print(f"Created: {met_json_path}")

        # Summary
        print(f"\n=== HySDS Metadata Created ===")
        print(f"Dataset: {dataset_name}")
        print(f"Files created: 2 ({dataset_name}.dataset.json, {dataset_name}.met.json)")

        if stac_metadata:
            print(f"STAC Catalog: {stac_metadata.get('catalog_id')}")
            print(f"Total Items: {stac_metadata.get('item_count', 0)}")

    except Exception as e:
        print(f"Error creating HySDS metadata: {e}")
        raise
