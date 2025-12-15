import logging

import os
import json  # Import the json library
import argparse
import pathlib
from pystac import Catalog

LOGGER = logging.getLogger(__name__)


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

    try:

        # Read and parse the STAC catalog
        catalog = Catalog.from_file(catalog_path)
        LOGGER.info(f"Successfully parsed STAC catalog: {catalog.id}")
        # Extract STAC Items from the catalog
        items = list(catalog.get_items(recursive=True))
        LOGGER.info(f"Found {len(items)} STAC Items in catalog")

        conversion_results = []

        # Process each STAC Item
        for item in items:
            try:
                LOGGER.info(f"Processing STAC Item: {item.id}")

                # Create directory for the item if it doesn't exist
                item_dir = os.path.join(output_dir, item.id)
                os.makedirs(item_dir, exist_ok=True)

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
        LOGGER.info(f"  Total Items: {len(items)}")
        LOGGER.info(f"  Successful: {successful}")
        LOGGER.info(f"  Failed: {failed}")

        if failed > 0:
            LOGGER.warning("\nFailed Items:")
            for result in conversion_results:
                if result["status"] == "error":
                    LOGGER.warning(f"  - {result['item_id']}: {result['error']}")

        return conversion_results

    except Exception as catalog_error:
        error_msg = f"Failed to process STAC catalog: {str(catalog_error)}"
        LOGGER.exception(f"ERROR: {error_msg}")
        raise Exception(error_msg)
