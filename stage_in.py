import pystac
import os
import json  # Import the json library
import argparse
import pathlib
import boto3
import requests
import urllib.parse
from datetime import datetime, timedelta, timezone
from maap.maap import MAAP

CMR_COLLECTIONS_URL = "https://cmr.earthdata.nasa.gov/search/collections.umm_json"
# Set STAGE_IN_DIRECT_S3=false to always use https for DAAC assets.
DIRECT_S3_ENABLED = os.environ.get("STAGE_IN_DIRECT_S3", "true").lower() not in ("0", "false", "no")
_CREDS_REFRESH_MARGIN = timedelta(minutes=5)
_DEFAULT_CREDS_LIFETIME = timedelta(minutes=30)

# endpoint -> (credentials dict, refresh_after datetime)
_daac_creds_cache = {}
# (provider, short_name, version) -> DirectDistributionInformation dict or None
_daac_info_cache = {}

_maap = None


def _get_maap():
    """Create the MAAP client on first use so jobs without file downloads make no API call."""
    global _maap
    if _maap is None:
        _maap = MAAP()
    return _maap


def _is_daac_s3(href):
    """True for s3:// hrefs outside the MAAP buckets (i.e. DAAC-hosted data)."""
    return href.startswith("s3://") and not href.startswith("s3://maap-")


def _cmr_ref_from_item(item):
    """
    Derive (provider, short_name, version) from a CMR-STAC item, or None.

    CMR STAC collection links look like .../stac/<PROVIDER>/collections/<SHORT_NAME>_<VERSION>.
    """
    for link in item.links:
        if link.rel not in ("collection", "parent"):
            continue
        parts = urllib.parse.urlparse(link.get_href() or "").path.strip("/").split("/")
        if "stac" in parts and "collections" in parts:
            i = parts.index("collections")
            if i >= 1 and i + 1 < len(parts) and "_" in parts[i + 1] and parts[i - 1] != "stac":
                short_name, version = parts[i + 1].rsplit("_", 1)
                return parts[i - 1], short_name, version
    return None


def _direct_distribution_info(cmr_ref):
    """Look up the collection's DirectDistributionInformation (S3 endpoint, region, buckets) in CMR."""
    if cmr_ref in _daac_info_cache:
        return _daac_info_cache[cmr_ref]
    provider, short_name, version = cmr_ref
    info = None
    try:
        response = requests.get(
            CMR_COLLECTIONS_URL,
            params={"provider": provider, "short_name": short_name, "version": version, "page_size": 1},
            timeout=30,
        )
        response.raise_for_status()
        items = response.json().get("items", [])
        if items:
            info = items[0]["umm"].get("DirectDistributionInformation")
    except (requests.exceptions.RequestException, ValueError) as e:
        print(f"    CMR lookup for {short_name}.{version} failed: {e}")
    _daac_info_cache[cmr_ref] = info
    return info


def _daac_credentials(endpoint):
    """Temporary DAAC S3 credentials for an s3credentials endpoint, cached until shortly before expiry."""
    cached = _daac_creds_cache.get(endpoint)
    if cached and datetime.now(timezone.utc) < cached[1]:
        return cached[0]
    creds = _get_maap().aws.earthdata_s3_credentials(endpoint)
    try:
        expires = datetime.fromisoformat(str(creds["expiration"]).replace("Z", "+00:00"))
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        refresh_after = expires - _CREDS_REFRESH_MARGIN
    except (KeyError, ValueError):
        refresh_after = datetime.now(timezone.utc) + _DEFAULT_CREDS_LIFETIME
    _daac_creds_cache[endpoint] = (creds, refresh_after)
    return creds


def _download_daac_s3(href, destination_path, cmr_ref):
    """Download a DAAC s3:// object using the DAAC's temporary credentials. Raises if not possible."""
    if not DIRECT_S3_ENABLED:
        raise RuntimeError("direct DAAC S3 access disabled (STAGE_IN_DIRECT_S3)")
    if cmr_ref is None:
        raise RuntimeError("cannot determine the CMR collection for this item")
    info = _direct_distribution_info(cmr_ref)
    endpoint = (info or {}).get("S3CredentialsAPIEndpoint")
    if not endpoint:
        raise RuntimeError("collection has no S3CredentialsAPIEndpoint in CMR")
    bucket, key = href[5:].split("/", 1)
    prefixes = (info or {}).get("S3BucketAndObjectPrefixNames") or []
    if prefixes and not any(bucket == p[5:].split("/", 1)[0] for p in prefixes if p.startswith("s3://")):
        raise RuntimeError(f"bucket '{bucket}' is not one of the collection's direct-access buckets")
    creds = _daac_credentials(endpoint)
    client = boto3.client(
        "s3",
        aws_access_key_id=creds["accessKeyId"],
        aws_secret_access_key=creds["secretAccessKey"],
        aws_session_token=creds["sessionToken"],
        region_name=info.get("Region", "us-west-2"),
    )
    dest = os.path.join(destination_path, os.path.basename(key))
    client.download_file(bucket, key, dest)
    return dest


def _download_asset(href, destination_path, cmr_ref=None):
    """Route asset download: MAAP S3 buckets use boto3, DAAC s3:// uses DAAC credentials,
    everything else uses maap.download_granule."""
    if href.startswith("s3://maap-"):
        parts = href[5:].split("/", 1)
        bucket, key = parts[0], parts[1]
        filename = os.path.basename(key)
        dest = os.path.join(destination_path, filename)
        boto3.client("s3").download_file(bucket, key, dest)
        return dest
    if _is_daac_s3(href):
        return _download_daac_s3(href, destination_path, cmr_ref)
    return _get_maap().download_granule(
        online_access_url=href,
        destination_path=destination_path,
        overwrite=True,
    )


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
    local_item.set_self_href(str(pathlib.Path(item_dir).resolve() / f"{item.id}.json"))

    print(f"Downloading assets for item: {item.id}")
    cmr_ref = _cmr_ref_from_item(item)
    https_by_name = {}
    for asset in item.assets.values():
        if asset.href.startswith(("http://", "https://")):
            https_by_name.setdefault(os.path.basename(asset.href), asset.href)
    fetched_via_s3 = {}  # file name -> local relative href, for files already fetched over direct S3

    # DAAC s3:// assets first, so an https asset for the same file can reuse the result
    ordered = sorted(item.assets.items(), key=lambda kv: not _is_daac_s3(kv[1].href))
    for asset_key, asset in ordered:
        href = asset.href
        name = os.path.basename(href)
        key_dir = asset_key.replace("/", "_")
        print(f"  Downloading asset '{asset_key}': {name}")
        if href.startswith(("http://", "https://")) and name in fetched_via_s3:
            print("    Already downloaded via direct S3, reusing")
            local_item.assets[asset_key].href = fetched_via_s3[name]
            continue
        try:
            asset_dir = os.path.join(item_dir, key_dir)
            os.makedirs(asset_dir, exist_ok=True)
            try:
                dest = _download_asset(href, asset_dir, cmr_ref)
                if _is_daac_s3(href):
                    fetched_via_s3[name] = os.path.join(key_dir, os.path.basename(dest))
            except Exception as e:
                fallback = https_by_name.get(name) if _is_daac_s3(href) else None
                if not fallback:
                    raise
                print(f"    Direct S3 failed ({e}); falling back to https")
                dest = _download_asset(fallback, asset_dir, cmr_ref)
            print("Download complete")
            local_item.assets[asset_key].href = os.path.join(key_dir, os.path.basename(dest))
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
