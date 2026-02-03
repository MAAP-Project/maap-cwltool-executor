import logging
import os
import sys
import json
import glob
import pathlib
import argparse
from typing import List, Dict, Any, Optional
from cwl_utils.parser import load_document_by_uri
from cwl_utils.parser.cwl_v1_2 import CommandLineTool, CommandOutputParameter
from pystac import Catalog, Item, Collection
import urllib.parse
import pystac

LOGGER = logging.getLogger(__name__)


def walk_stac_catalog_2(catalog_path: str) -> Dict[str, Any]:
    # Initialize catalog_data dictionary
    catalog_data = {}

    try:
        catalog_dir = os.path.dirname(catalog_path)
        # Read and parse the STAC catalog
        with open(catalog_path, 'r') as f:
            catalog_dict = json.loads(f.read())
        catalog = Catalog.from_dict(catalog_dict)
        LOGGER.info(f"Successfully parsed STAC catalog: {catalog.id}")

        # Populate catalog metadata
        catalog_data['id'] = catalog.id
        catalog_data['description'] = catalog.description or ''
        catalog_data['stac_object_type'] = catalog.STAC_OBJECT_TYPE
        catalog_data['catalog_path'] = catalog_path

        # If this is a collection, extract extent and other metadata
        if hasattr(catalog, 'extent'):
            catalog_data['extent'] = {
                'spatial': {'bbox': catalog.extent.spatial.bboxes} if catalog.extent.spatial else {},
                'temporal': {'interval': catalog.extent.temporal.intervals} if catalog.extent.temporal else {}
            }

        if hasattr(catalog, 'keywords'):
            catalog_data['keywords'] = catalog.keywords or []

        if hasattr(catalog, 'license'):
            catalog_data['license'] = catalog.license or ''

        # Validate STAC version is >= 1.1.0
        stac_version = catalog_dict.get('stac_version', '0.0.0')
        if not stac_version:
            raise ValueError("STAC catalog missing version information")

        # Parse version string to compare (e.g. "1.1.0" -> [1, 1, 0])
        try:
            version_parts = [int(x) for x in stac_version.split('.')]
            required_parts = [1, 0, 0]  # Version 1.1.0

            # Compare version parts
            if version_parts < required_parts:
                raise ValueError(f"STAC version {stac_version} is not supported. Required: >= 1.1.0")

            LOGGER.info(f"STAC version validation passed: {stac_version}")

        except ValueError as ve:
            if "not supported" in str(ve):
                raise ve
            raise ValueError(f"Invalid STAC version format '{stac_version}'. Expected format: X.Y.Z")

        # Extract STAC Items from the catalog (including items from collections)
        item_links = []

        # Get all child links from catalog
        all_links = [k for k in catalog.get_links() if k.rel in ['item', 'child', 'collection'] and not k.target.startswith('http')]

        LOGGER.info(f"Found {len(all_links)} total eligible links in catalog")
        for each in all_links:
            if os.path.isabs(each.target):
                continue
            each.target = os.path.join(catalog_dir, each.target)
            debug = 1
        for link in all_links:
            # Check if link exists locally
            if not os.path.exists(link.target):
                LOGGER.warning(f"Local link file not found: {link.target}")
                continue

            # Handle different link types
            if link.rel == 'item':
                # Direct item link
                item_links.append(link)
                LOGGER.info(f"Found item link: {link.target}")
            elif link.rel == 'child' or link.rel == 'collection':
                # Collection link - read collection and extract items
                try:
                    collection = Collection.from_file(link.target)
                    collection_item_links = list(collection.get_item_links())
                    collection_folder = os.path.dirname(link.target)
                    temp_item_links = [k for k in collection.get_links() if k.rel in ['item'] and not k.target.startswith('http')]
                    for each in temp_item_links:
                        if os.path.isabs(each.target):
                            continue
                        each.target = os.path.join(collection_folder, each.target)
                    item_links.extend(temp_item_links)
                    LOGGER.info(f"Found collection '{collection.id}' with {len(collection_item_links)} items: {link.target}")
                except Exception as e:
                    LOGGER.warning(f"Failed to process collection link '{link.target}': {str(e)}")
                    continue
            else:
                # Other link types - log and ignore
                LOGGER.info(f"Ignoring link of type '{link.rel}': {link.target}")

        LOGGER.info(f"Total STAC Items to process: {len(item_links)}")
        conversion_results = []
        items = []  # List to store item metadata for catalog_data

        # Process each STAC Item
        for item_link in item_links:
            try:
                item = Item.from_file(item_link.target)

                LOGGER.info(f"Processing STAC Item: {item.id}")

                # Build item metadata for catalog_data (before any modifications)
                item_metadata = {
                    'id': item.id,
                    'collection': item.collection_id,
                    'datetime': item.datetime.isoformat() if item.datetime else None,
                    'bbox': item.bbox,
                    'assets': {}
                }

                # Extract asset info for catalog_data
                for asset_name, asset in item.assets.items():
                    item_metadata['assets'][asset_name] = {
                        'href': asset.href,
                        'type': asset.media_type
                    }

                # Extract key properties
                item_metadata['properties'] = item.properties or {}

                # Add to items list
                items.append(item_metadata)

                # Create directory for the item if it doesn't exist
                item_dir = os.path.join(catalog_dir, item.id)
                os.makedirs(item_dir, exist_ok=True)

                # Update asset hrefs to be relative to the new item_dir location
                # Get the directory where the original item.json is located
                original_item_dir = os.path.dirname(item_link.target)

                # Update each asset's href to be relative to the new item_dir
                for asset_key, asset in item.assets.items():
                    original_href = asset.href

                    # Skip absolute URLs (http/https)
                    if original_href.startswith(('http://', 'https://')):
                        LOGGER.info(f"  Skipping remote asset: {original_href}")
                        continue

                    # Resolve the asset's absolute path from the original item location
                    if os.path.isabs(original_href):
                        # Already absolute path
                        asset_absolute_path = original_href
                    else:
                        # Relative path - resolve from original item.json location
                        asset_absolute_path = os.path.abspath(
                            os.path.join(original_item_dir, original_href)
                        )

                    # Calculate new relative path from item_dir to the asset
                    new_relative_href = os.path.relpath(asset_absolute_path, item_dir)

                    # Update the asset href
                    asset.href = new_relative_href
                    LOGGER.info(f"  Updated asset '{asset_key}': {original_href} -> {new_relative_href}")

                conversion_results.append({
                    "item_id": item.id,
                    "status": "success",
                    "item_dir": item_dir
                })

            except Exception as item_error:
                error_msg = f"Failed to process STAC Item '{item.id}': {str(item_error)}"
                LOGGER.exception(f"ERROR: {error_msg}")
                conversion_results.append({
                    "item_id": item.id,
                    "status": "error",
                    "error": error_msg
                })
                continue

        # Summary of conversion results
        successful = len([r for r in conversion_results if r["status"] == "success"])
        failed = len([r for r in conversion_results if r["status"] == "error"])

        LOGGER.info(f"\nConversion Summary:")
        LOGGER.info(f"  Total Items: {len(item_links)}")
        LOGGER.info(f"  Successful: {successful}")
        LOGGER.info(f"  Failed: {failed}")

        if failed > 0:
            LOGGER.warning("\nFailed Items:")
            for result in conversion_results:
                if result["status"] == "error":
                    LOGGER.warning(f"  - {result['item_id']}: {result['error']}")

        # Add items list and count to catalog_data
        catalog_data['items'] = items
        catalog_data['item_count'] = len(items)

        # Return both catalog_data and conversion_results
        return {
            'catalog_data': catalog_data,
            'conversion_results': conversion_results
        }

    except Exception as catalog_error:
        error_msg = f"Failed to process STAC catalog: {str(catalog_error)}"
        LOGGER.exception(f"ERROR: {error_msg}")
        raise RuntimeError(error_msg)


def get_id_from_uri(uri):
    """Extract ID from CWL URI fragment"""
    fragment = urllib.parse.urlparse(uri).fragment
    return os.path.basename(fragment)


def parse_cwl_outputs(cwl_file_path: str) -> List[CommandOutputParameter]:
    """
    Parse CWL file and extract output definitions
    
    Args:
        cwl_file_path (str): Path to the CWL file
        
    Returns:
        List of CommandOutputParameter objects
    """
    print(f"Parsing CWL outputs from: {cwl_file_path}")
    
    try:
        # Load the CWL document
        uri = str(pathlib.Path(cwl_file_path).resolve().as_uri()) if not cwl_file_path.startswith("file://") else cwl_file_path
        cwl_object = load_document_by_uri(uri)
        
        if isinstance(cwl_object, CommandLineTool):
            if not cwl_object.outputs:
                print("No outputs defined in CWL file")
                return []
            
            print(f"Found {len(cwl_object.outputs)} output(s) in CWL:")
            for output in cwl_object.outputs:
                output_id = get_id_from_uri(output.id)
                print(f"  - {output_id}: {output.type_}")
                
            return cwl_object.outputs
        else:
            print(f"Error: CWL document is not a CommandLineTool (type: {type(cwl_object).__name__})")
            return []
            
    except Exception as e:
        print(f"Error parsing CWL file: {e}")
        return []


def resolve_output_paths(cwl_outputs: List[CommandOutputParameter]) -> Dict[str, Dict[str, Any]]:
    """
    Resolve actual output file/directory paths using CWL output definitions
    
    Args:
        cwl_outputs: List of CWL output parameters
        
    Returns:
        Dictionary mapping output names to their resolved paths and metadata
    """
    output_paths = {}
    
    for output in cwl_outputs:
        output_id = get_id_from_uri(output.id)
        output_type = output.type_
        
        # Default glob pattern if not specified
        glob_pattern = output_id
        
        # Extract glob pattern from outputBinding if available
        if hasattr(output, 'outputBinding') and output.outputBinding:
            if hasattr(output.outputBinding, 'glob') and output.outputBinding.glob:
                glob_pattern = output.outputBinding.glob
        
        print(f"Resolving output '{output_id}' with pattern '{glob_pattern}'")
        
        # Find matching files/directories
        matches = glob.glob(glob_pattern)
        
        if matches:
            # Take the first match (or could handle multiple matches differently)
            resolved_path = matches[0]
            print(f"  Found: {resolved_path}")
            
            output_paths[output_id] = {
                'path': resolved_path,
                'type': output_type,
                'glob': glob_pattern,
                'is_directory': os.path.isdir(resolved_path)
            }
        else:
            print(f"  Warning: No files found matching pattern '{glob_pattern}'")
            
    return output_paths


def is_stac_catalog(directory_path: str) -> bool:
    """
    Check if a directory contains a STAC catalog
    
    Args:
        directory_path: Path to directory to check
        
    Returns:
        True if directory appears to be a STAC catalog
    """
    if not os.path.isdir(directory_path):
        return False
        
    # Look for catalog.json or collection.json
    catalog_files = ['catalog.json', 'collection.json']
    for catalog_file in catalog_files:
        catalog_path = os.path.join(directory_path, catalog_file)
        if os.path.exists(catalog_path):
            try:
                with open(catalog_path, 'r') as f:
                    data = json.load(f)
                    # Basic STAC validation - check for required fields
                    if 'type' in data and data['type'] in ['Catalog', 'Collection']:
                        return True
            except (json.JSONDecodeError, KeyError):
                continue
                
    return False


def extract_stac_metadata(output_dir: str) -> Optional[Dict[str, Any]]:
    """
    Extract comprehensive STAC metadata from an output directory

    Args:
        output_dir: Path to output directory containing catalog.json

    Returns:
        Dictionary with complete STAC catalog metadata or None if not a STAC catalog
    """
    # Find the catalog file
    catalog_file = None
    for filename in ['catalog.json', 'collection.json']:
        potential_path = os.path.join(output_dir, filename)
        if os.path.exists(potential_path):
            catalog_file = potential_path
            break

    if not catalog_file:
        return None

    # Validate it's a STAC catalog
    try:
        with open(catalog_file, 'r') as f:
            data = json.load(f)
            if 'type' not in data or data['type'] not in ['Catalog', 'Collection']:
                return None
    except:
        return None

    # Walk the catalog and extract metadata
    catalog_metadata = walk_stac_catalog_2(catalog_file)
    if not catalog_metadata:
        return None
    catalog_metadata = catalog_metadata['catalog_data']
    return {
        'is_stac': True,
        'catalog_id': catalog_metadata.get('id'),
        'catalog_path': catalog_metadata.get('catalog_path'),
        'stac_version': catalog_metadata.get('stac_version'),
        'stac_object_type': catalog_metadata.get('stac_object_type'),
        'description': catalog_metadata.get('description'),
        'item_count': catalog_metadata.get('item_count', 0),
        'extent': catalog_metadata.get('extent'),
        'keywords': catalog_metadata.get('keywords', []),
        'license': catalog_metadata.get('license', ''),
        'items': catalog_metadata.get('items', [])
    }


def stage_out_outputs(cwl_file_path: str, base_output_dir: str = "output") -> Dict[str, Any]:
    """
    Main stage-out function that discovers and processes CWL outputs

    Args:
        cwl_file_path: Path to the CWL file
        base_output_dir: Base output directory name (fallback)

    Returns:
        Dictionary with:
        - 'outputs': List of output info dicts (each with output_id, output_dir, stac_metadata if applicable)
        - 'primary_output': The first output directory (for backward compatibility)
    """
    print(f"\n=== Stage Out Process ===")
    print(f"CWL file: {cwl_file_path}")
    print(f"Fallback output dir: {base_output_dir}")

    # Parse CWL outputs
    cwl_outputs = parse_cwl_outputs(cwl_file_path)

    outputs_list = []

    if not cwl_outputs:
        print("No CWL outputs found, falling back to default behavior")
        if os.path.exists(base_output_dir):
            return {
                'outputs': [],
                'primary_output': base_output_dir
            }
        return {
            'outputs': [],
            'primary_output': None
        }

    # Resolve actual output paths
    output_paths = resolve_output_paths(cwl_outputs)

    if not output_paths:
        print("No output files found, falling back to default behavior")
        if os.path.exists(base_output_dir):
            return {
                'outputs': [],
                'primary_output': base_output_dir
            }
        return {
            'outputs': [],
            'primary_output': None
        }

    # Process each output
    print(f"\n=== Stage Out Summary ===")
    print(f"Total outputs discovered: {len(output_paths)}")

    for output_id, output_info in output_paths.items():
        output_dir = output_info['path']
        is_directory = output_info['is_directory']

        print(f"  {output_id}: {output_dir} ({output_info['type']})")
        output_dict = {
            'output_id': output_id,
            'output_dir': output_dir,
            'output_type': output_info['type'],
            'is_directory': is_directory
        }
        # Extract STAC metadata if this is a directory that's a STAC catalog
        if is_directory:
            stac_metadata = extract_stac_metadata(output_dir)
            if stac_metadata:
                output_dict['stac_metadata'] = stac_metadata
                print(f"    STAC: {stac_metadata['stac_object_type']} - {stac_metadata['description']}")
                print(f"    Items: {stac_metadata['item_count']}")

        outputs_list.append(output_dict)

    # Get the primary output (first one)
    first_output = next(iter(output_paths.values()))
    primary_output_path = first_output['path']

    # If it's a file, return its directory
    if not first_output['is_directory']:
        primary_output_path = os.path.dirname(primary_output_path)

    print(f"Primary output directory: {primary_output_path}")

    return {
        'outputs': outputs_list,
        'primary_output': primary_output_path
    }


def main():
    """Command line interface for stage_out"""
    parser = argparse.ArgumentParser(
        description="Stage out CWL outputs and discover actual output paths"
    )
    parser.add_argument(
        "cwl_file",
        help="Path to the CWL file"
    )
    parser.add_argument(
        "--base-output-dir",
        default="output",
        help="Base output directory for fallback (default: output)"
    )
    parser.add_argument(
        "--json-output",
        action="store_true",
        help="Output results as JSON"
    )

    args = parser.parse_args()

    result = stage_out_outputs(args.cwl_file, args.base_output_dir)

    if args.json_output:
        # Output in JSON format for shell script consumption
        print(json.dumps(result))
    else:
        # Human-readable output
        if result['primary_output']:
            print(f"\nPrimary output directory: {result['primary_output']}")
        else:
            print("\nNo outputs found")
            sys.exit(1)


if __name__ == "__main__":
    main()

# Sample: python stage_out.py '/Users/wphyo/Projects/unity/maap-cwltool-executor/example_workflow.cwl'

# dataset_publish.py

# https://hysds-core.atlassian.net/wiki/spaces/HYS/pages/199853166/Hello+Dataset-+Installation-+Github