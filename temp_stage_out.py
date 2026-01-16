import logging

import os
import json  # Import the json library
import argparse
from typing import Any, Dict

from pystac import Catalog, Item, Collection

LOGGER = logging.getLogger(__name__)


def walk_stac_catalog(catalog_path: str) -> Dict[str, Any]:
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
            required_parts = [1, 1, 0]  # Version 1.1.0

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

                # Generate <item_id>.met.json with complete STAC Item metadata
                met_path = os.path.join(item_dir, f"{item.id}.met.json")
                with open(met_path, 'w') as met_file:
                    json.dump(item.to_dict(), met_file, indent=2)
                LOGGER.info(f"Created metadata file: {met_path}")

                # Generate <item_id>.dataset.json with HySDS dataset configuration
                dataset_config = {
                    "version": "v1.0",
                    "dataset_type": item.collection_id if item.collection_id else "unknown-collection",
                    "label": item.properties.get("title", item.id)
                }

                dataset_path = os.path.join(item_dir, f"{item.id}.dataset.json")
                with open(dataset_path, 'w') as dataset_file:
                    json.dump(dataset_config, dataset_file, indent=2)
                LOGGER.info(f"Created dataset file: {dataset_path}")

                conversion_results.append({
                    "item_id": item.id,
                    "status": "success",
                    "met_file": met_path,
                    "dataset_file": dataset_path
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


def convert_stac_to_hysds_in_ogc_app_pack(output_dir):
    """
    ### Requirements
#### Input
- Local STAC catalog with a `catalog.json` file in the output directory
- STAC specification: **1.1.0**
- Structure: **Flat catalog** (no nested catalogs or collections)
#### Output
For each STAC Item in the catalog, create two files:
1. `<item_name>.met.json` - Contains the complete STAC Item metadata
2. `<item_name>.dataset.json` - Contains HySDS dataset configuration
#### Functional Requirements
1. **STAC Catalog Processing**
   - Locate and read `catalog.json` in the output directory
   - Parse STAC Items from the catalog (STAC 1.1.0 format)
   - Iterate through each Item in the catalog
2. **HySDS Dataset Creation**
   - For each STAC Item, create a directory named after the Item ID
   - Generate `<item_id>.met.json`:
     - Include the entire STAC Item JSON as-is
     - Preserve all STAC properties and metadata unchanged
   - Generate `<item_id>.dataset.json`:
     - Map STAC Collection ID (if present) to HySDS `dataset_type` field
     - Include standard HySDS dataset configuration fields
3. **Directory Structure Preservation**
   - Maintain the existing STAC catalog directory structure
   - Do NOT move, copy, or relocate any data files referenced in STAC assets
   - Only create the `.met.json` and `.dataset.json` files alongside existing data
4. **Error Handling**
   - Validate that `catalog.json` exists
   - Handle missing or malformed STAC Items gracefully
   - Log errors for Items that fail conversion
   - Support partial success (some Items convert successfully while others fail)
   - Provide clear error messages for debugging
#### File Format Examples
**Example `<item_id>.met.json`:**
```json
{
  "type": "Feature",
  "stac_version": "1.1.0",
  "id": "example-item-001",
  "geometry": { ... },
  "properties": { ... },
  "collection": "example-collection",
  "links": [ ... ],
  "assets": { ... }
}
```
**Example `<item_id>.dataset.json`:**
```json
{
  "version": "v1.0",
  "dataset_type": "example-collection",
  "label": "Example Item 001"
}
```
    :param output_dir:
    :return:
    """
    # Validate that catalog.json exists in output directory
    catalog_path = os.path.join(output_dir, "catalog.json")
    if not os.path.exists(catalog_path):
        raise FileNotFoundError(f"STAC catalog.json not found at: {catalog_path}")

    LOGGER.info(f"Found STAC catalog at: {catalog_path}")
    result = walk_stac_catalog(catalog_path)

    # Return conversion_results for backward compatibility
    # (catalog_data is also available in result['catalog_data'] if needed)
    return result.get('conversion_results', [])



if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--output-dir", type=str, default="local_stac_catalog",
                    help="The directory to save the local STAC catalog")
    args = vars(ap.parse_args())
    convert_stac_to_hysds_in_ogc_app_pack(output_dir=args["output_dir"])