import os
import json
import tempfile
import unittest
from pathlib import Path
import sys
from datetime import datetime

# Add parent directory to path to import stage_out
sys.path.insert(0, str(Path(__file__).parent.parent))

import stage_out


class TestStageOut(unittest.TestCase):
    """Test cases for stage_out.py"""

    def test_stage_out_with_stac_catalog_and_multiple_outputs(self):
        """
        Comprehensive test: stage out with STAC catalog, collection, items, and multiple outputs
        """
        # Create a temporary directory for our test
        with tempfile.TemporaryDirectory() as tmpdir:
            # Change to the temp directory so glob patterns work
            original_cwd = os.getcwd()
            os.chdir(tmpdir)

            try:
                # Create output directories
                stac_output_dir = os.path.join(tmpdir, "stac_results")
                os.makedirs(stac_output_dir)

                # Create a STAC catalog structure
                catalog_data = {
                    "stac_version": "1.0.0",
                    "type": "Catalog",
                    "id": "test-catalog",
                    "description": "Test STAC catalog for unit testing",
                    "links": [
                        {
                            "rel": "root",
                            "href": "./catalog.json",
                            "type": "application/json"
                        },
                        {
                            "rel": "item",
                            "href": "./item1.json",
                            "type": "application/json"
                        },
                        {
                            "rel": "item",
                            "href": "./item2.json",
                            "type": "application/json"
                        }
                    ]
                }

                catalog_file = os.path.join(stac_output_dir, "catalog.json")
                with open(catalog_file, 'w') as f:
                    json.dump(catalog_data, f, indent=2)

                # Create STAC item files
                item1_data = {
                    "stac_version": "1.0.0",
                    "type": "Feature",
                    "id": "test-item-001",
                    "collection": "test-collection",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[
                            [-180, -90], [180, -90], [180, 90], [-180, 90], [-180, -90]
                        ]]
                    },
                    "bbox": [-180, -90, 180, 90],
                    "properties": {
                        "datetime": "2024-01-15T12:00:00Z",
                        "title": "Test Item 1",
                        "description": "A test STAC item"
                    },
                    "assets": {
                        "data": {
                            "href": "./data1.tif",
                            "type": "image/tiff",
                            "title": "Test Data File"
                        },
                        "metadata": {
                            "href": "./metadata1.json",
                            "type": "application/json",
                            "title": "Metadata"
                        }
                    },
                    "links": [
                        {
                            "rel": "root",
                            "href": "./catalog.json",
                            "type": "application/json"
                        },
                        {
                            "rel": "parent",
                            "href": "./catalog.json",
                            "type": "application/json"
                        }
                    ]
                }

                item1_file = os.path.join(stac_output_dir, "item1.json")
                with open(item1_file, 'w') as f:
                    json.dump(item1_data, f, indent=2)

                # Create second STAC item
                item2_data = {
                    "stac_version": "1.0.0",
                    "type": "Feature",
                    "id": "test-item-002",
                    "collection": "test-collection",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [0, 0]
                    },
                    "bbox": [-1, -1, 1, 1],
                    "properties": {
                        "datetime": "2024-01-16T12:00:00Z",
                        "title": "Test Item 2"
                    },
                    "assets": {
                        "data": {
                            "href": "./data2.tif",
                            "type": "image/tiff"
                        }
                    },
                    "links": []
                }

                item2_file = os.path.join(stac_output_dir, "item2.json")
                with open(item2_file, 'w') as f:
                    json.dump(item2_data, f, indent=2)

                # Create a simple text file output
                simple_output_file = os.path.join(tmpdir, "summary.txt")
                with open(simple_output_file, 'w') as f:
                    f.write("Processing completed successfully\n")

                # Create a CWL file with multiple outputs including STAC directory
                cwl_content = {
                    "cwlVersion": "v1.2",
                    "class": "CommandLineTool",
                    "baseCommand": ["process"],
                    "inputs": {},
                    "outputs": {
                        "stac_catalog": {
                            "type": "Directory",
                            "outputBinding": {
                                "glob": "stac_results"
                            }
                        },
                        "summary": {
                            "type": "File",
                            "outputBinding": {
                                "glob": "summary.txt"
                            }
                        }
                    }
                }

                cwl_file = os.path.join(tmpdir, "test_workflow.cwl")
                with open(cwl_file, 'w') as f:
                    json.dump(cwl_content, f)

                # Run stage_out_outputs
                result = stage_out.stage_out_outputs(cwl_file)
                print(json.dumps(result, indent=4))
                # Verify the results
                self.assertIsNotNone(result)
                self.assertIn('outputs', result)
                self.assertIn('primary_output', result)

                # Should have two outputs
                self.assertEqual(len(result['outputs']), 2)

                # Find the STAC catalog output
                stac_output = None
                file_output = None
                for output in result['outputs']:
                    if output['output_id'] == 'stac_catalog':
                        stac_output = output
                    elif output['output_id'] == 'summary':
                        file_output = output

                # Verify STAC catalog output
                self.assertIsNotNone(stac_output, "STAC catalog output should be found")
                self.assertEqual(stac_output['output_type'], 'Directory')
                self.assertTrue(stac_output['is_directory'])
                self.assertIn('stac_metadata', stac_output, "STAC metadata should be extracted")

                # Verify STAC metadata details
                stac_meta = stac_output['stac_metadata']
                self.assertTrue(stac_meta['is_stac'])
                self.assertEqual(stac_meta['catalog_id'], 'test-catalog')
                self.assertEqual(stac_meta['stac_object_type'], 'Catalog')
                self.assertEqual(stac_meta['description'], 'Test STAC catalog for unit testing')
                self.assertEqual(stac_meta['item_count'], 2, "Should find 2 STAC items")

                # Verify items were discovered
                self.assertIsNotNone(stac_meta['items'])
                self.assertEqual(len(stac_meta['items']), 2)

                # Check item details
                item_ids = [item['id'] for item in stac_meta['items']]
                self.assertIn('test-item-001', item_ids)
                self.assertIn('test-item-002', item_ids)

                # Verify first item has assets
                item1 = next(item for item in stac_meta['items'] if item['id'] == 'test-item-001')
                self.assertIn('assets', item1)
                self.assertIn('data', item1['assets'])
                self.assertIn('metadata', item1['assets'])

                # Verify file output
                self.assertIsNotNone(file_output, "File output should be found")
                self.assertEqual(file_output['output_type'], 'File')
                self.assertFalse(file_output['is_directory'])
                self.assertEqual(file_output['output_dir'], os.path.basename(simple_output_file))

                # Verify primary output is set
                self.assertIsNotNone(result['primary_output'])

            finally:
                # Restore original working directory
                os.chdir(original_cwd)

if __name__ == '__main__':
    unittest.main()
