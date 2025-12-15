from unittest import TestCase


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
        return
