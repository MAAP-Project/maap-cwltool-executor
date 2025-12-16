from unittest import TestCase
import tempfile
import os
import json
import pystac
from pystac import Link, RelType, MediaType

from stage_out import convert_stac_to_hysds_in_ogc_app_pack


class TestStageOut(TestCase):
    def test_01(self):
        """
        - Create a temp directory. There should be a built-in library
        - create an output directory
        - create a folder MY_COLLECTION
        - create a STAC feature file MY_ITEM_1 in MY_COLLECTION directory that has MY_ITEM_1.dat, MY_ITEM_1.img as assets in output directory
        - create a STAC feature file MY_ITEM_2 in MY_COLLECTION directory that has MY_ITEM_2.dat, MY_ITEM_2.img, MY_ITEM_2.tiff as assets in output directory
        - create a STAC feature file MY_ITEM_3 in MY_COLLECTION directory that has MY_ITEM_3.dat as asset in output directory
        - all 3 features has MY_COLLECTION as collection, and stac version 1.1
        - use pystac.Item class to create them and write them as files.
        - asset URLs should be relative
        - create respective asset as empty files with respective names in the output directory
        - create a catalog file in output directory with pystac.CATALOG
        - add 3 items as item links with relative URLs.
        - Run convert_stac_to_hysds_in_ogc_app_pack method with output directory
        - Check 3 ITEM ID folders are created.
        - Check .met.json and .dataset.json are created in each of them.
        - check each .met.json is the STAC feature.
        - check .dataset.json follows this example json by creating a schema.
                {
                  "version": "v1.0",
                  "dataset_type": "example-collection",
                  "label": "Example Item 001"
                }
        - print the result files and folders
        :return:
        """
        # Create a temp directory
        with tempfile.TemporaryDirectory() as temp_dir:
            print(f"Created temp directory: {temp_dir}")

            # Create output directory
            output_dir = os.path.join(temp_dir, "output")
            os.makedirs(output_dir, exist_ok=True)
            print(f"Created output directory: {output_dir}")

            # Create MY_COLLECTION folder
            collection_dir = os.path.join(output_dir, "MY_COLLECTION")
            os.makedirs(collection_dir, exist_ok=True)
            print(f"Created collection directory: {collection_dir}")

            # Define asset configurations for each item
            items_config = {
                "MY_ITEM_1": ["MY_ITEM_1.dat", "MY_ITEM_1.img"],
                "MY_ITEM_2": ["MY_ITEM_2.dat", "MY_ITEM_2.img", "MY_ITEM_2.tiff"],
                "MY_ITEM_3": ["MY_ITEM_3.dat"]
            }

            # Create empty asset files in output directory
            all_assets = []
            for item_id, asset_names in items_config.items():
                for asset_name in asset_names:
                    asset_path = os.path.join(output_dir, asset_name)
                    with open(asset_path, 'w') as f:
                        pass  # Create empty file
                    all_assets.append(asset_path)
                    print(f"Created asset file: {asset_path}")

            # Create STAC Items
            items = []
            for item_id, asset_names in items_config.items():
                # Create assets dictionary with relative URLs
                assets = {}
                for asset_name in asset_names:
                    assets[asset_name.split('.')[1]] = pystac.Asset(
                        href=f"./{asset_name}",  # Relative URL
                        title=asset_name
                    )

                # Create STAC Item
                item = pystac.Item(
                    id=item_id,
                    geometry={
                        "type": "Polygon",
                        "coordinates": [[
                            [-180, -90], [180, -90], [180, 90], [-180, 90], [-180, -90]
                        ]]
                    },
                    bbox=[-180, -90, 180, 90],
                    datetime=None,
                    properties={
                        "title": f"Test Item {item_id}",
                        "start_datetime": "2023-01-01T00:00:00Z",
                        "end_datetime": "2023-01-02T00:00:00Z"
                    },
                    assets=assets,
                    collection="MY_COLLECTION",
                    stac_extensions=[]
                )

                # Write item to file in MY_COLLECTION directory
                item_path = os.path.join(collection_dir, f"{item_id}.json")
                item.save_object(True, item_path)
                items.append(item)
                print(f"Created STAC item file: {item_path}")

            # Create catalog file in output directory
            catalog = pystac.Catalog(
                id="test-catalog",
                description="Test catalog for STAC to HySDS conversion",
                stac_extensions=[]
            )

            # Add items to catalog with relative URLs
            for item in items:
                # Set relative link to item
                item_href = f"./MY_COLLECTION/{item.id}.json"
                catalog.add_link(Link(RelType.ITEM, item_href, MediaType.GEOJSON, item.properties.get('title')))
                print(f"Added item to catalog: {item.id} -> {item_href}")

            # Save catalog to output directory
            catalog_path = os.path.join(output_dir, "catalog.json")
            catalog.save_object(True, catalog_path)
            print(f"Created catalog file: {catalog_path}")

            # Run convert_stac_to_hysds_in_ogc_app_pack method
            print(f"\nRunning conversion on output directory: {output_dir}")
            results = convert_stac_to_hysds_in_ogc_app_pack(output_dir)

            # Validate results
            print(f"\nValidation Results:")
            self.assertEqual(len(results), 3, "Should have 3 conversion results")

            # Check 3 ITEM ID folders are created
            expected_item_dirs = ["MY_ITEM_1", "MY_ITEM_2", "MY_ITEM_3"]
            for item_id in expected_item_dirs:
                item_dir = os.path.join(output_dir, item_id)
                self.assertTrue(os.path.exists(item_dir), f"Item directory should exist: {item_dir}")
                print(f"✓ Item directory exists: {item_dir}")

            # Check .met.json and .dataset.json are created in each directory
            for item_id in expected_item_dirs:
                item_dir = os.path.join(output_dir, item_id)

                # Check .met.json file
                met_path = os.path.join(item_dir, f"{item_id}.met.json")
                self.assertTrue(os.path.exists(met_path), f"Met file should exist: {met_path}")
                print(f"✓ Met file exists: {met_path}")

                # Check .dataset.json file
                dataset_path = os.path.join(item_dir, f"{item_id}.dataset.json")
                self.assertTrue(os.path.exists(dataset_path), f"Dataset file should exist: {dataset_path}")
                print(f"✓ Dataset file exists: {dataset_path}")

                # Validate .met.json contains the STAC feature
                with open(met_path, 'r') as f:
                    met_content = json.load(f)

                self.assertEqual(met_content['type'], 'Feature', "Met file should be a STAC Feature")
                self.assertEqual(met_content['id'], item_id, f"Met file should have correct ID: {item_id}")
                self.assertEqual(met_content['collection'], 'MY_COLLECTION', "Met file should have correct collection")
                print(f"✓ Met file content validated for: {item_id}")

                # Validate .dataset.json follows the expected schema
                with open(dataset_path, 'r') as f:
                    dataset_content = json.load(f)

                expected_schema = {
                    "version": "v1.0",
                    "dataset_type": "MY_COLLECTION",
                    "label": f"Test Item {item_id}"
                }

                self.assertEqual(dataset_content['version'], expected_schema['version'])
                self.assertEqual(dataset_content['dataset_type'], expected_schema['dataset_type'])
                self.assertEqual(dataset_content['label'], expected_schema['label'])
                print(f"✓ Dataset file content validated for: {item_id}")

            # Print result files and folders
            print(f"\n=== RESULT FILES AND FOLDERS ===")
            print(f"Temp directory: {temp_dir}")
            print(f"Output directory: {output_dir}")
            print(f"Conversion results: {len([r for r in results if r['status'] == 'success'])} successful, {len([r for r in results if r['status'] == 'error'])} failed")

            print(f"\nDirectory structure:")
            for root, dirs, files in os.walk(output_dir):
                level = root.replace(output_dir, '').count(os.sep)
                indent = ' ' * 2 * level
                print(f"{indent}{os.path.basename(root)}/")
                subindent = ' ' * 2 * (level + 1)
                for file in files:
                    print(f"{subindent}{file}")

            print(f"\n✅ All tests passed!")
        return results

    def test_02(self):
        """
        - Create a temp directory. There should be a built-in library
        - create an output directory
        - create a folder MY_COLLECTION
        - create a STAC feature file MY_ITEM_1 in MY_COLLECTION directory that has MY_ITEM_1.dat, MY_ITEM_1.img as assets in output directory
        - create a STAC feature file MY_ITEM_2 in MY_COLLECTION directory that has MY_ITEM_2.dat, MY_ITEM_2.img, MY_ITEM_2.tiff as assets in output directory
        - create a STAC feature file MY_ITEM_3 in MY_COLLECTION directory that has MY_ITEM_3.dat as asset in output directory
        - all 3 features has MY_COLLECTION as collection, and stac version 1.1
        - use pystac.Item class to create them and write them as files.
        - asset URLs should be relative
        - create respective asset as empty files with respective names in the output directory
        - create a catalog file in output directory with pystac.CATALOG
        - add 3 items as item links with relative URLs.
        - Run convert_stac_to_hysds_in_ogc_app_pack method with output directory
        - Check 3 ITEM ID folders are created.
        - Check .met.json and .dataset.json are created in each of them.
        - check each .met.json is the STAC feature.
        - check .dataset.json follows this example json by creating a schema.
                {
                  "version": "v1.0",
                  "dataset_type": "example-collection",
                  "label": "Example Item 001"
                }
        - print the result files and folders
        :return:
        """
        # Create a temp directory
        with tempfile.TemporaryDirectory() as temp_dir:
            print(f"Created temp directory: {temp_dir}")

            # Create output directory
            output_dir = os.path.join(temp_dir, "output")
            os.makedirs(output_dir, exist_ok=True)
            print(f"Created output directory: {output_dir}")

            # Create MY_COLLECTION folder
            collection_dir = os.path.join(output_dir, "MY_COLLECTION")
            os.makedirs(collection_dir, exist_ok=True)
            print(f"Created collection directory: {collection_dir}")

            # Define asset configurations for each item
            items_config = {
                "MY_ITEM_1": ["MY_ITEM_1.dat", "MY_ITEM_1.img"],
                "MY_ITEM_2": ["MY_ITEM_2.dat", "MY_ITEM_2.img", "MY_ITEM_2.tiff"],
                "MY_ITEM_3": ["MY_ITEM_3.dat"]
            }

            # Create empty asset files in output directory
            all_assets = []
            for item_id, asset_names in items_config.items():
                for asset_name in asset_names:
                    asset_path = os.path.join(output_dir, asset_name)
                    with open(asset_path, 'w') as f:
                        pass  # Create empty file
                    all_assets.append(asset_path)
                    print(f"Created asset file: {asset_path}")

            # Create STAC Items
            items = []
            for item_id, asset_names in items_config.items():
                # Create assets dictionary with relative URLs
                assets = {}
                for asset_name in asset_names:
                    assets[asset_name.split('.')[1]] = pystac.Asset(
                        href=f"./{asset_name}",  # Relative URL
                        title=asset_name
                    )

                # Create STAC Item
                item = pystac.Item(
                    id=item_id,
                    geometry={
                        "type": "Polygon",
                        "coordinates": [[
                            [-180, -90], [180, -90], [180, 90], [-180, 90], [-180, -90]
                        ]]
                    },
                    bbox=[-180, -90, 180, 90],
                    datetime=None,
                    properties={
                        "title": f"Test Item {item_id}",
                        "start_datetime": "2023-01-01T00:00:00Z",
                        "end_datetime": "2023-01-02T00:00:00Z"
                    },
                    assets=assets,
                    collection="MY_COLLECTION",
                    stac_extensions=[]
                )

                # Write item to file in MY_COLLECTION directory
                item_path = os.path.join(collection_dir, f"{item_id}.json")
                item.save_object(True, item_path)
                items.append(item)
                print(f"Created STAC item file: {item_path}")

            # Create catalog file in output directory
            catalog = pystac.Catalog(
                id="test-catalog",
                description="Test catalog for STAC to HySDS conversion",
                stac_extensions=[]
            )

            # Add items to catalog with relative URLs
            for item in items:
                # Set relative link to item
                item_href = f"./MY_COLLECTION/{item.id}.json"
                catalog.add_link(Link(RelType.ITEM, item_href, MediaType.GEOJSON, item.properties.get('title')))
                print(f"Added item to catalog: {item.id} -> {item_href}")

            # Save catalog to output directory
            catalog_path = os.path.join(output_dir, "catalog.json")
            catalog_dict = catalog.to_dict(True, False)
            catalog_dict['stac_version'] = '1.0.0'
            with open(catalog_path, 'w') as ff:
                ff.write(json.dumps(catalog_dict, indent=4))
            print(f"Created catalog file: {catalog_path}")

            # Run convert_stac_to_hysds_in_ogc_app_pack method
            print(f"\nRunning conversion on output directory: {output_dir}")
            with self.assertRaises(RuntimeError) as cm:
                results = convert_stac_to_hysds_in_ogc_app_pack(output_dir)
                self.assertTrue(str(cm.exception) == 'Failed to process STAC catalog: STAC version 1.0.0 is not supported. Required: >= 1.1.0')
            print(f"\n✅ All tests passed!")
        return

    def test_03(self):
        """
        Enhanced test with collections:
        - Create catalog with 3 direct items (like test_01)
        - Add child link to COLLECTION_1 with 3 items
        - Add collection link to COLLECTION_2 with 3 items
        - Total of 9 items to process
        - Include proper self and root links
        :return:
        """
        # Create a temp directory
        with tempfile.TemporaryDirectory() as temp_dir:
            print(f"Created temp directory: {temp_dir}")

            # Create output directory
            output_dir = os.path.join(temp_dir, "output")
            os.makedirs(output_dir, exist_ok=True)
            print(f"Created output directory: {output_dir}")

            # Create MY_COLLECTION folder (for direct items)
            collection_dir = os.path.join(output_dir, "MY_COLLECTION")
            os.makedirs(collection_dir, exist_ok=True)
            print(f"Created direct items collection directory: {collection_dir}")

            # Create COLLECTION_1 and COLLECTION_2 directories with items subfolders
            collection1_dir = os.path.join(output_dir, "COLLECTION_1")
            collection1_items_dir = os.path.join(collection1_dir, "items")
            os.makedirs(collection1_items_dir, exist_ok=True)
            print(f"Created collection 1 directory: {collection1_dir}")

            collection2_dir = os.path.join(output_dir, "COLLECTION_2")
            collection2_items_dir = os.path.join(collection2_dir, "items")
            os.makedirs(collection2_items_dir, exist_ok=True)
            print(f"Created collection 2 directory: {collection2_dir}")

            # Define asset configurations for all items
            all_items_config = {
                # Direct items (same as test_01)
                "MY_ITEM_1": ["MY_ITEM_1.dat", "MY_ITEM_1.img"],
                "MY_ITEM_2": ["MY_ITEM_2.dat", "MY_ITEM_2.img", "MY_ITEM_2.tiff"],
                "MY_ITEM_3": ["MY_ITEM_3.dat"],
                # Collection 1 items
                "COLL1_ITEM_1": ["COLL1_ITEM_1.dat", "COLL1_ITEM_1.img"],
                "COLL1_ITEM_2": ["COLL1_ITEM_2.dat", "COLL1_ITEM_2.img", "COLL1_ITEM_2.tiff"],
                "COLL1_ITEM_3": ["COLL1_ITEM_3.dat"],
                # Collection 2 items
                "COLL2_ITEM_1": ["COLL2_ITEM_1.dat", "COLL2_ITEM_1.img"],
                "COLL2_ITEM_2": ["COLL2_ITEM_2.dat", "COLL2_ITEM_2.img", "COLL2_ITEM_2.tiff"],
                "COLL2_ITEM_3": ["COLL2_ITEM_3.dat"]
            }

            # Create empty asset files in output directory
            for item_id, asset_names in all_items_config.items():
                for asset_name in asset_names:
                    asset_path = os.path.join(output_dir, asset_name)
                    with open(asset_path, 'w') as f:
                        pass  # Create empty file
                    print(f"Created asset file: {asset_path}")

            # Create direct STAC Items (MY_COLLECTION)
            direct_items = []
            direct_items_config = {
                "MY_ITEM_1": ["MY_ITEM_1.dat", "MY_ITEM_1.img"],
                "MY_ITEM_2": ["MY_ITEM_2.dat", "MY_ITEM_2.img", "MY_ITEM_2.tiff"],
                "MY_ITEM_3": ["MY_ITEM_3.dat"]
            }

            for item_id, asset_names in direct_items_config.items():
                assets = {}
                for asset_name in asset_names:
                    assets[asset_name.split('.')[1]] = pystac.Asset(
                        href=f"./{asset_name}",  # Relative URL
                        title=asset_name
                    )

                item = pystac.Item(
                    id=item_id,
                    geometry={
                        "type": "Polygon",
                        "coordinates": [[
                            [-180, -90], [180, -90], [180, 90], [-180, 90], [-180, -90]
                        ]]
                    },
                    bbox=[-180, -90, 180, 90],
                    datetime=None,
                    properties={
                        "title": f"Test Item {item_id}",
                        "start_datetime": "2023-01-01T00:00:00Z",
                        "end_datetime": "2023-01-02T00:00:00Z"
                    },
                    assets=assets,
                    collection="MY_COLLECTION",
                    stac_extensions=[]
                )

                item_path = os.path.join(collection_dir, f"{item_id}.json")
                item.save_object(True, item_path)
                direct_items.append(item)
                print(f"Created direct STAC item file: {item_path}")

            # Create Collection 1 items
            coll1_items = []
            coll1_items_config = {
                "COLL1_ITEM_1": ["COLL1_ITEM_1.dat", "COLL1_ITEM_1.img"],
                "COLL1_ITEM_2": ["COLL1_ITEM_2.dat", "COLL1_ITEM_2.img", "COLL1_ITEM_2.tiff"],
                "COLL1_ITEM_3": ["COLL1_ITEM_3.dat"]
            }

            for item_id, asset_names in coll1_items_config.items():
                assets = {}
                for asset_name in asset_names:
                    assets[asset_name.split('.')[1]] = pystac.Asset(
                        href=f"../../{asset_name}",  # Relative to collection/items/
                        title=asset_name
                    )

                item = pystac.Item(
                    id=item_id,
                    geometry={
                        "type": "Polygon",
                        "coordinates": [[
                            [-180, -90], [180, -90], [180, 90], [-180, 90], [-180, -90]
                        ]]
                    },
                    bbox=[-180, -90, 180, 90],
                    datetime=None,
                    properties={
                        "title": f"Collection 1 Item {item_id}",
                        "start_datetime": "2023-01-01T00:00:00Z",
                        "end_datetime": "2023-01-02T00:00:00Z"
                    },
                    assets=assets,
                    collection="COLLECTION_1",
                    stac_extensions=[]
                )

                item_path = os.path.join(collection1_items_dir, f"{item_id}.json")
                item.save_object(True, item_path)
                coll1_items.append(item)
                print(f"Created collection 1 item file: {item_path}")

            # Create Collection 2 items
            coll2_items = []
            coll2_items_config = {
                "COLL2_ITEM_1": ["COLL2_ITEM_1.dat", "COLL2_ITEM_1.img"],
                "COLL2_ITEM_2": ["COLL2_ITEM_2.dat", "COLL2_ITEM_2.img", "COLL2_ITEM_2.tiff"],
                "COLL2_ITEM_3": ["COLL2_ITEM_3.dat"]
            }

            for item_id, asset_names in coll2_items_config.items():
                assets = {}
                for asset_name in asset_names:
                    assets[asset_name.split('.')[1]] = pystac.Asset(
                        href=f"../../{asset_name}",  # Relative to collection/items/
                        title=asset_name
                    )

                item = pystac.Item(
                    id=item_id,
                    geometry={
                        "type": "Polygon",
                        "coordinates": [[
                            [-180, -90], [180, -90], [180, 90], [-180, 90], [-180, -90]
                        ]]
                    },
                    bbox=[-180, -90, 180, 90],
                    datetime=None,
                    properties={
                        "title": f"Collection 2 Item {item_id}",
                        "start_datetime": "2023-01-01T00:00:00Z",
                        "end_datetime": "2023-01-02T00:00:00Z"
                    },
                    assets=assets,
                    collection="COLLECTION_2",
                    stac_extensions=[]
                )

                item_path = os.path.join(collection2_items_dir, f"{item_id}.json")
                item.save_object(True, item_path)
                coll2_items.append(item)
                print(f"Created collection 2 item file: {item_path}")

            # Create Collection 1 collection.json
            collection1 = pystac.Collection(
                id="COLLECTION_1",
                description="Test Collection 1 with 3 items",
                extent=pystac.Extent(
                    spatial=pystac.SpatialExtent([[-180, -90, 180, 90]]),
                    temporal=pystac.TemporalExtent([[None, None]])
                ),
                stac_extensions=[]
            )

            # Add self and root links to collection 1
            collection1.add_link(Link(pystac.RelType.SELF, "./collection.json", MediaType.JSON, "Self link"))
            collection1.add_link(Link(pystac.RelType.ROOT, "../catalog.json", MediaType.JSON, "Root catalog"))

            # Add item links to collection 1
            for item in coll1_items:
                item_href = f"./items/{item.id}.json"
                collection1.add_link(Link(pystac.RelType.ITEM, item_href, MediaType.GEOJSON, item.properties.get('title')))

            collection1_path = os.path.join(collection1_dir, "collection.json")
            collection1.save_object(True, collection1_path)
            print(f"Created collection 1 file: {collection1_path}")

            # Create Collection 2 collection.json
            collection2 = pystac.Collection(
                id="COLLECTION_2",
                description="Test Collection 2 with 3 items",
                extent=pystac.Extent(
                    spatial=pystac.SpatialExtent([[-180, -90, 180, 90]]),
                    temporal=pystac.TemporalExtent([[None, None]])
                ),
                stac_extensions=[]
            )

            # Add self and root links to collection 2
            collection2.add_link(Link(pystac.RelType.SELF, "./collection.json", MediaType.JSON, "Self link"))
            collection2.add_link(Link(pystac.RelType.ROOT, "../catalog.json", MediaType.JSON, "Root catalog"))

            # Add item links to collection 2
            for item in coll2_items:
                item_href = f"./items/{item.id}.json"
                collection2.add_link(Link(pystac.RelType.ITEM, item_href, MediaType.GEOJSON, item.properties.get('title')))

            collection2_path = os.path.join(collection2_dir, "collection.json")
            collection2.save_object(True, collection2_path)
            print(f"Created collection 2 file: {collection2_path}")

            # Create main catalog file
            catalog = pystac.Catalog(
                id="test-catalog-with-collections",
                description="Test catalog with direct items and collections",
                stac_extensions=[]
            )

            # Add self and root links to catalog
            catalog.add_link(Link(pystac.RelType.SELF, "./catalog.json", MediaType.JSON, "Self link"))
            catalog.add_link(Link(pystac.RelType.ROOT, "./catalog.json", MediaType.JSON, "Root catalog"))

            # Add direct item links to catalog
            for item in direct_items:
                item_href = f"./MY_COLLECTION/{item.id}.json"
                catalog.add_link(Link(pystac.RelType.ITEM, item_href, MediaType.GEOJSON, item.properties.get('title')))
                print(f"Added direct item to catalog: {item.id} -> {item_href}")

            # Add child link to Collection 1
            catalog.add_link(Link(pystac.RelType.CHILD, "./COLLECTION_1/collection.json", MediaType.JSON, "Collection 1"))
            print(f"Added child link to Collection 1")

            # Add collection link to Collection 2
            catalog.add_link(Link("collection", "./COLLECTION_2/collection.json", MediaType.JSON, "Collection 2"))
            print(f"Added collection link to Collection 2")

            # Save catalog to output directory
            catalog_path = os.path.join(output_dir, "catalog.json")
            catalog.save_object(True, catalog_path)
            print(f"Created catalog file: {catalog_path}")

            # Run convert_stac_to_hysds_in_ogc_app_pack method
            print(f"\nRunning conversion on output directory: {output_dir}")
            results = convert_stac_to_hysds_in_ogc_app_pack(output_dir)

            # Validate results
            print(f"\nValidation Results:")
            self.assertEqual(len(results), 9, "Should have 9 conversion results (3 direct + 3 from coll1 + 3 from coll2)")

            # Check all 9 ITEM ID folders are created
            expected_item_ids = [
                "MY_ITEM_1", "MY_ITEM_2", "MY_ITEM_3",           # Direct items
                "COLL1_ITEM_1", "COLL1_ITEM_2", "COLL1_ITEM_3", # Collection 1 items
                "COLL2_ITEM_1", "COLL2_ITEM_2", "COLL2_ITEM_3"  # Collection 2 items
            ]

            for item_id in expected_item_ids:
                item_dir = os.path.join(output_dir, item_id)
                self.assertTrue(os.path.exists(item_dir), f"Item directory should exist: {item_dir}")
                print(f"✓ Item directory exists: {item_dir}")

                # Check .met.json and .dataset.json files
                met_path = os.path.join(item_dir, f"{item_id}.met.json")
                dataset_path = os.path.join(item_dir, f"{item_id}.dataset.json")

                self.assertTrue(os.path.exists(met_path), f"Met file should exist: {met_path}")
                self.assertTrue(os.path.exists(dataset_path), f"Dataset file should exist: {dataset_path}")

                # Validate .met.json content
                with open(met_path, 'r') as f:
                    met_content = json.load(f)

                self.assertEqual(met_content['type'], 'Feature', f"Met file should be a STAC Feature: {item_id}")
                self.assertEqual(met_content['id'], item_id, f"Met file should have correct ID: {item_id}")

                # Validate .dataset.json content
                with open(dataset_path, 'r') as f:
                    dataset_content = json.load(f)

                # Determine expected collection based on item_id
                if item_id.startswith("MY_ITEM"):
                    expected_collection = "MY_COLLECTION"
                elif item_id.startswith("COLL1_ITEM"):
                    expected_collection = "COLLECTION_1"
                elif item_id.startswith("COLL2_ITEM"):
                    expected_collection = "COLLECTION_2"

                self.assertEqual(dataset_content['version'], "v1.0")
                self.assertEqual(dataset_content['dataset_type'], expected_collection)
                print(f"✓ Files validated for: {item_id} (collection: {expected_collection})")

            # Print result summary
            print(f"\n=== RESULT SUMMARY ===")
            print(f"Total items processed: {len(results)}")
            print(f"Successful conversions: {len([r for r in results if r['status'] == 'success'])}")
            print(f"Failed conversions: {len([r for r in results if r['status'] == 'error'])}")

            print(f"\nDirectory structure:")
            for root, dirs, files in os.walk(output_dir):
                level = root.replace(output_dir, '').count(os.sep)
                indent = ' ' * 2 * level
                print(f"{indent}{os.path.basename(root)}/")
                subindent = ' ' * 2 * (level + 1)
                for file in files:
                    print(f"{subindent}{file}")

            print(f"\n✅ All tests passed! Successfully processed 9 items from catalog with collections.")

        return results


