import os
import sys
import json
import glob
import shutil
import pathlib
import argparse
from typing import List, Dict, Any, Optional
from cwl_utils.parser import load_document_by_uri
from cwl_utils.parser.cwl_v1_2 import CommandLineTool, CommandOutputParameter
import urllib.parse
import pystac

from temp_stage_out import walk_stac_catalog as walk_stac_catalog_2

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


def get_item_metadata(item_path: str) -> Optional[Dict[str, Any]]:
    """
    Extract metadata from a STAC Item JSON file

    Args:
        item_path: Path to STAC Item JSON file

    Returns:
        Dictionary with item metadata (id, collection, datetime, bbox, assets, properties)
        or None if file cannot be read
    """
    try:
        with open(item_path, 'r') as f:
            item_json = json.load(f)

        # Extract key fields for inventory
        return {
            'id': item_json.get('id'),
            'collection': item_json.get('collection'),
            'datetime': item_json.get('properties', {}).get('datetime'),
            'bbox': item_json.get('bbox'),
            'assets': item_json.get('assets', {}),
            'properties': item_json.get('properties', {})
        }
    except Exception as e:
        print(f"  Warning: Could not read item {item_path}: {e}")
        return None


def walk_stac_catalog(catalog_path: str) -> Dict[str, Any]:
    """
    Walk a STAC catalog and extract comprehensive metadata

    Args:
        catalog_path: Path to catalog.json or collection.json file

    Returns:
        Dictionary with catalog structure including all items
    """
    catalog_data = {}

    try:
        # Load the catalog using pystac
        stac_object = pystac.read_file(catalog_path)

        # Ensure it's a Catalog or Collection (which support get_items)
        if not isinstance(stac_object, (pystac.Catalog, pystac.Collection)):
            print(f"  Warning: STAC object is not a Catalog or Collection (type: {type(stac_object).__name__})")
            return catalog_data

        catalog = stac_object

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

        # Collect all items from the catalog
        items = []

        # Use pystac's get_items() to walk and collect items
        try:
            for item in catalog.get_items(recursive=True):
                item_metadata = {
                    'id': item.id,
                    'collection': item.collection_id,
                    'datetime': item.datetime.isoformat() if item.datetime else None,
                    'bbox': item.bbox,
                    'assets': {}
                }

                # Extract asset info
                for asset_name, asset in item.assets.items():
                    item_metadata['assets'][asset_name] = {
                        'href': asset.href,
                        'type': asset.media_type
                    }

                # Extract key properties
                item_metadata['properties'] = item.properties or {}

                items.append(item_metadata)
        except Exception as e:
            print(f"  Warning: Could not iterate items: {e}")

        catalog_data['items'] = items
        catalog_data['item_count'] = len(items)

    except Exception as e:
        print(f"  Warning: Error walking STAC catalog {catalog_path}: {e}")

    return catalog_data


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


def catalog_stac_outputs(output_paths: Dict[str, Dict[str, Any]]) -> Dict[str, str]:
    """
    Process Directory outputs that are STAC catalogs

    Args:
        output_paths: Dictionary of resolved output paths

    Returns:
        Dictionary mapping output names to their catalog descriptions
    """
    stac_catalogs = {}

    for output_id, output_info in output_paths.items():
        if output_info['is_directory'] and output_info['type'] == 'Directory':
            directory_path = output_info['path']

            if is_stac_catalog(directory_path):
                print(f"Processing STAC catalog: {directory_path}")

                try:
                    # Try to load and validate the catalog
                    catalog_file = None
                    for filename in ['catalog.json', 'collection.json']:
                        potential_path = os.path.join(directory_path, filename)
                        if os.path.exists(potential_path):
                            catalog_file = potential_path
                            break

                    if catalog_file:
                        stac_object = pystac.read_file(catalog_file)
                        if isinstance(stac_object, (pystac.Catalog, pystac.Collection)):
                            stac_catalogs[output_id] = f"STAC {stac_object.STAC_OBJECT_TYPE}: {stac_object.description or 'No description'}"
                            print(f"  Valid STAC catalog: {stac_object.id}")
                        else:
                            stac_catalogs[output_id] = f"STAC object (unexpected type: {type(stac_object).__name__})"
                            print(f"  Warning: Unexpected STAC object type: {type(stac_object).__name__}")
                    else:
                        stac_catalogs[output_id] = "STAC catalog (no main catalog file found)"

                except Exception as e:
                    print(f"  Warning: Error validating STAC catalog: {e}")
                    stac_catalogs[output_id] = f"STAC catalog (validation error: {e})"
            else:
                print(f"Directory output '{output_id}' is not a STAC catalog")

    return stac_catalogs


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


def debug_main():
    result = stage_out_outputs('/Users/wphyo/Projects/unity/maap-cwltool-executor/example_workflow.cwl')
    print(json.dumps(result))
    if result['primary_output']:
        print(f"\nPrimary output directory: {result['primary_output']}")
    else:
        print("\nNo outputs found")
        sys.exit(1)
    return

if __name__ == "__main__":
    # main()
    debug_main()
