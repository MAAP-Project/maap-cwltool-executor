import pystac
import os
import json  # Import the json library
import argparse
import pathlib
from maap.maap import MAAP

maap = MAAP()


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
        # Load the item data from the provided JSON
        item = pystac.Item.from_dict(item_json_data)

        # Create the output directory if it doesn't exist
        os.makedirs(output_dir, exist_ok=True)
        item_dir = os.path.join(output_dir, item.id)
        os.makedirs(item_dir, exist_ok=True)
        local_item = pystac.Item(
            id=item.id,
            geometry=item.geometry,
            bbox=item.bbox,
            datetime=item.datetime,
            properties=item.properties,
        )
        local_item.set_self_href(str(pathlib.Path(item_dir).resolve()))

        print(f"Downloading assets for item: {item.id}")
        # Download each asset
        for asset_key, asset in item.assets.items():
            href = asset.href
            print(f"  Downloading asset '{asset_key}': {os.path.basename(href)}")
            try:
                dest = maap.downloadGranule(online_access_url=href, destination_path=item_dir, overwrite=True)
                print("Download complete")
                local_asset = pystac.Asset(href=dest, media_type=asset.media_type)
                local_item.add_asset(asset_key, local_asset)
            except Exception as e:
                print(f"    Error downloading {asset_key}: {e}")

        # Create a simple local STAC catalog
        catalog = pystac.Catalog(id="local-downloaded-catalog",
                                 description="A local catalog containing downloaded STAC item assets.")

        catalog.add_item(local_item)
        # Save the catalog
        catalog_path = os.path.join(output_dir, "catalog.json")
        catalog.normalize_hrefs(output_dir)
        catalog.save(catalog_type=pystac.CatalogType.SELF_CONTAINED)
        print(f"\nLocal STAC catalog created at: {catalog_path}")

    except Exception as e:
        print(f"An error occurred: {e}")


def main(stac_item_filepath, output_dir="local_stac_catalog"):
    """
    Loads item from json and creates a local STAC catalog.
    :param stac_item_filepath:
    :param output_dir:
    :return:
    """
    stac_item_data = json.load(open(stac_item_filepath))
    download_stac_item_assets_from_json(stac_item_data, output_dir=output_dir)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--stac-item-filepath", type=str, required=True,
                    help="The path to the STAC item JSON file")
    ap.add_argument("--output-dir", type=str, default="local_stac_catalog",
                    help="The directory to save the local STAC catalog")
    args = vars(ap.parse_args())
    main(stac_item_filepath=args["stac_item_filepath"], output_dir=args["output_dir"])
