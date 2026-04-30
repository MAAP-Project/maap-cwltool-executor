import pystac
import os
import json  # Import the json library
import argparse
import pathlib
from datetime import datetime
from maap.maap import MAAP

maap = MAAP()


def _download_single_item(item_json_data, output_dir, parent_container):
    """
    Downloads assets for a single STAC item and adds it to the parent container.

    Args:
        item_json_data (dict): A dictionary containing the STAC item's JSON data.
        output_dir (str): Directory to save downloaded assets.
        parent_container: A pystac.Catalog or pystac.Collection to add the item to.

    Returns:
        pystac.Item: The local item with downloaded assets.
    """
    item = pystac.Item.from_dict(item_json_data)
    item_dir = os.path.join(output_dir, item.id)
    os.makedirs(item_dir, exist_ok=True)

    # Deep-copy the item so all metadata (extra_fields, stac_extensions, etc.) is preserved,
    # then replace remote links/hrefs with local paths.
    local_item = item.clone()
    # pystac.clone() preserves stac_extensions but not extra_fields, so restore them explicitly
    local_item.extra_fields.update(item.extra_fields)
    local_item.clear_links()
    local_item.set_self_href(str(pathlib.Path(item_dir).resolve()))

    print(f"Downloading assets for item: {item.id}")
    for asset_key, asset in item.assets.items():
        href = asset.href
        print(f"  Downloading asset '{asset_key}': {os.path.basename(href)}")
        try:
            dest = maap.downloadGranule(online_access_url=href, destination_path=os.path.dirname(item_dir),
                                        overwrite=True)
            print("Download complete")
            local_item.assets[asset_key].href = os.path.basename(dest)
        except Exception as e:
            print(f"    Error downloading {asset_key}: {e}")
            local_item.assets.pop(asset_key, None)

    local_item.make_asset_hrefs_relative()
    parent_container.add_item(local_item)
    return local_item


def _build_collection(collection_json_data, output_dir):
    """
    Build a pystac.Collection from FeatureCollection metadata.

    Args:
        collection_json_data (dict): A dictionary containing the FeatureCollection data.
        output_dir (str): Directory where the collection will be stored.

    Returns:
        pystac.Collection: A collection with metadata derived from the FeatureCollection.
    """
    collection_id = collection_json_data.get("id", "local-downloaded-collection")
    description = collection_json_data.get("description", "A local collection containing downloaded STAC items.")

    # Derive extent from features
    features = collection_json_data.get("features", [])
    all_bboxes = []
    all_datetimes = []

    for feature in features:
        if feature.get("bbox"):
            all_bboxes.append(feature["bbox"])
        if feature.get("properties", {}).get("datetime"):
            all_datetimes.append(feature["properties"]["datetime"])

    # Compute spatial extent
    if all_bboxes:
        min_x = min(bbox[0] for bbox in all_bboxes)
        min_y = min(bbox[1] for bbox in all_bboxes)
        max_x = max(bbox[2] for bbox in all_bboxes)
        max_y = max(bbox[3] for bbox in all_bboxes)
        spatial_extent = [[min_x, min_y, max_x, max_y]]
    else:
        spatial_extent = [[-180, -90, 180, 90]]

    # Compute temporal extent
    if all_datetimes:
        # Parse datetime strings to datetime objects
        parsed_datetimes = []
        for dt_str in all_datetimes:
            try:
                # Handle ISO 8601 format with Z suffix
                if isinstance(dt_str, str):
                    dt_str = dt_str.replace('Z', '+00:00')
                    parsed_datetimes.append(datetime.fromisoformat(dt_str))
                else:
                    parsed_datetimes.append(dt_str)
            except (ValueError, AttributeError):
                # Skip unparseable datetimes
                continue

        if parsed_datetimes:
            parsed_datetimes.sort()
            temporal_extent = [[parsed_datetimes[0], parsed_datetimes[-1]]]
        else:
            temporal_extent = [[None, None]]
    else:
        temporal_extent = [[None, None]]

    # Create extent
    extent = pystac.Extent(
        spatial=pystac.SpatialExtent(spatial_extent),
        temporal=pystac.TemporalExtent(temporal_extent)
    )

    collection_dir = os.path.join(output_dir, collection_id)
    os.makedirs(collection_dir, exist_ok=True)
    collection_path = os.path.join(collection_dir, "collection.json")

    collection = pystac.Collection(
        id=collection_id,
        description=description,
        extent=extent,
        catalog_type=pystac.CatalogType.SELF_CONTAINED,
        href=collection_path
    )

    return collection


def download_stac_item_assets_from_json(item_json_data, output_dir="local_stac_catalog"):
    """
    Downloads all assets from a STAC item, given the item's JSON data,
    and creates a local STAC catalog.

    Args:
        item_json_data (dict):  A dictionary containing the STAC item's JSON data.
        output_dir (str, optional): Directory to save the downloaded assets
                                     and the local STAC catalog.
                                     Defaults to "local_stac_catalog".
    """
    try:
        # Create the output directory if it doesn't exist
        os.makedirs(output_dir, exist_ok=True)

        # Create a simple local STAC catalog
        catalog_path = os.path.join(output_dir, "catalog.json")
        catalog = pystac.Catalog(id="local-downloaded-catalog",
                                 description="A local catalog containing downloaded STAC item assets.",
                                 catalog_type=pystac.CatalogType.SELF_CONTAINED,
                                 href=catalog_path)

        _download_single_item(item_json_data, output_dir, catalog)

        # Save the catalog
        catalog.save()
        print(f"\nLocal STAC catalog created at: {catalog_path}")

    except Exception as e:
        print(f"An error occurred: {e}")


def download_stac_collection_assets_from_json(collection_json_data, output_dir="local_stac_catalog"):
    """
    Downloads all assets from all items in a STAC collection (FeatureCollection),
    and creates a local STAC catalog with a nested collection structure.

    Args:
        collection_json_data (dict): A dictionary containing the FeatureCollection's JSON data.
        output_dir (str, optional): Directory to save the downloaded assets
                                     and the local STAC catalog.
                                     Defaults to "local_stac_catalog".
    """
    try:
        # Create the output directory if it doesn't exist
        os.makedirs(output_dir, exist_ok=True)

        # Create root catalog
        catalog_path = os.path.join(output_dir, "catalog.json")
        root_catalog = pystac.Catalog(id="local-downloaded-catalog",
                                      description="A local catalog containing downloaded STAC collections.",
                                      catalog_type=pystac.CatalogType.SELF_CONTAINED,
                                      href=catalog_path)

        # Create collection from FeatureCollection metadata
        collection = _build_collection(collection_json_data, output_dir)

        # Download assets for each feature and add to collection
        features = collection_json_data.get("features", [])
        print(f"Processing FeatureCollection with {len(features)} items")
        for feature in features:
            _download_single_item(feature, output_dir, collection)

        # Add collection to root catalog and save
        root_catalog.add_child(collection)
        root_catalog.save()
        print(f"\nLocal STAC catalog created at: {catalog_path}")

    except Exception as e:
        print(f"An error occurred: {e}")


def download_stac_assets_from_json(json_data, output_dir="local_stac_catalog"):
    """
    Detects the type of GeoJSON input (Feature or FeatureCollection) and
    downloads assets accordingly.

    Args:
        json_data (dict): A dictionary containing either a GeoJSON Feature or FeatureCollection.
        output_dir (str, optional): Directory to save the downloaded assets
                                     and the local STAC catalog.
                                     Defaults to "local_stac_catalog".

    Raises:
        ValueError: If the GeoJSON type is unsupported.
    """
    geojson_type = json_data.get("type")

    if geojson_type == "FeatureCollection":
        download_stac_collection_assets_from_json(json_data, output_dir)
    elif geojson_type == "Feature":
        download_stac_item_assets_from_json(json_data, output_dir)
    else:
        raise ValueError(f"Unsupported GeoJSON type: {geojson_type}")


def main(stac_item_filepath, output_dir="local_stac_catalog"):
    """
    Loads a GeoJSON file (Feature or FeatureCollection) and creates a local STAC catalog.
    :param stac_item_filepath:
    :param output_dir:
    :return:
    """
    stac_data = json.load(open(stac_item_filepath))
    download_stac_assets_from_json(stac_data, output_dir=output_dir)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--stac-item-filepath", type=str, required=True,
                    help="The path to the STAC item JSON file")
    ap.add_argument("--output-dir", type=str, default="local_stac_catalog",
                    help="The directory to save the local STAC catalog")
    args = vars(ap.parse_args())
    main(stac_item_filepath=args["stac_item_filepath"], output_dir=args["output_dir"])
