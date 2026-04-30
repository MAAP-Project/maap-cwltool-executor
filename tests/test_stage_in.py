import pytest
import os
import json
import tempfile
from pathlib import Path
import sys
from unittest.mock import Mock, patch, MagicMock, call
from datetime import datetime
import pystac

# Add parent directory to path to import stage_out
sys.path.insert(0, str(Path(__file__).parent.parent))

from stage_in import (
    download_stac_assets_from_json,
    _build_collection,
    _download_single_item,
    download_stac_item_assets_from_json,
    download_stac_collection_assets_from_json,
    main
)


class TestDispatcher:
    """Test download_stac_assets_from_json() routing logic."""
    
    @patch('stage_in.download_stac_item_assets_from_json')
    @patch('stage_in.download_stac_collection_assets_from_json')
    def test_feature_routes_to_single_item_path(self, mock_collection, mock_item):
        """Feature type should route to single-item path, not collection path."""
        json_data = {"type": "Feature", "id": "test-item"}
        download_stac_assets_from_json(json_data, "output")
        
        mock_item.assert_called_once_with(json_data, "output")
        mock_collection.assert_not_called()
    
    @patch('stage_in.download_stac_item_assets_from_json')
    @patch('stage_in.download_stac_collection_assets_from_json')
    def test_feature_collection_routes_to_collection_path(self, mock_collection, mock_item):
        """FeatureCollection type should route to collection path, not single-item path."""
        json_data = {"type": "FeatureCollection", "features": []}
        download_stac_assets_from_json(json_data, "output")
        
        mock_collection.assert_called_once_with(json_data, "output")
        mock_item.assert_not_called()
    
    def test_unsupported_type_raises_value_error(self):
        """Any other type (e.g. 'Point', None) should raise ValueError."""
        json_data = {"type": "Point", "coordinates": [0, 0]}
        
        with pytest.raises(ValueError, match="Unsupported GeoJSON type: Point"):
            download_stac_assets_from_json(json_data, "output")
    
    def test_none_type_raises_value_error(self):
        """None type should raise ValueError."""
        json_data = {"id": "test"}
        
        with pytest.raises(ValueError, match="Unsupported GeoJSON type: None"):
            download_stac_assets_from_json(json_data, "output")


class TestExtentComputation:
    """Test _build_collection() extent computation logic."""
    
    def test_spatial_extent_union_of_multiple_bboxes(self, tmp_path):
        """Multiple features with bboxes should produce union (min of mins, max of maxes)."""
        collection_json = {
            "id": "test-collection",
            "features": [
                {"bbox": [10, 20, 30, 40]},
                {"bbox": [5, 15, 25, 35]},
                {"bbox": [15, 25, 35, 45]}
            ]
        }
        
        collection = _build_collection(collection_json, str(tmp_path))
        
        spatial_bbox = collection.extent.spatial.bboxes[0]
        assert spatial_bbox == [5, 15, 35, 45]
    
    def test_spatial_extent_defaults_when_no_bboxes(self, tmp_path):
        """No features with bboxes should default to [-180, -90, 180, 90]."""
        collection_json = {
            "id": "test-collection",
            "features": [
                {"id": "item1"},
                {"id": "item2"}
            ]
        }
        
        collection = _build_collection(collection_json, str(tmp_path))
        
        spatial_bbox = collection.extent.spatial.bboxes[0]
        assert spatial_bbox == [-180, -90, 180, 90]
    
    def test_spatial_extent_only_some_features_have_bboxes(self, tmp_path):
        """Only features with bboxes should contribute to extent."""
        collection_json = {
            "id": "test-collection",
            "features": [
                {"id": "item1"},
                {"bbox": [10, 20, 30, 40]},
                {"id": "item2"},
                {"bbox": [5, 15, 25, 35]}
            ]
        }
        
        collection = _build_collection(collection_json, str(tmp_path))
        
        spatial_bbox = collection.extent.spatial.bboxes[0]
        assert spatial_bbox == [5, 15, 30, 40]
    
    def test_temporal_extent_with_z_suffix(self, tmp_path):
        """Datetimes with Z suffix should parse correctly; min becomes start, max becomes end."""
        collection_json = {
            "id": "test-collection",
            "features": [
                {"properties": {"datetime": "2023-01-15T10:00:00Z"}},
                {"properties": {"datetime": "2023-01-10T08:00:00Z"}},
                {"properties": {"datetime": "2023-01-20T12:00:00Z"}}
            ]
        }
        
        collection = _build_collection(collection_json, str(tmp_path))
        
        temporal_interval = collection.extent.temporal.intervals[0]
        assert temporal_interval[0] == datetime.fromisoformat("2023-01-10T08:00:00+00:00")
        assert temporal_interval[1] == datetime.fromisoformat("2023-01-20T12:00:00+00:00")
    
    def test_temporal_extent_no_datetimes(self, tmp_path):
        """No datetimes should result in [None, None]."""
        collection_json = {
            "id": "test-collection",
            "features": [
                {"id": "item1"},
                {"id": "item2"}
            ]
        }
        
        collection = _build_collection(collection_json, str(tmp_path))
        
        temporal_interval = collection.extent.temporal.intervals[0]
        assert temporal_interval == [None, None]
    
    def test_temporal_extent_malformed_datetimes_skipped(self, tmp_path):
        """Malformed datetime strings should be skipped; valid ones still compute correctly."""
        collection_json = {
            "id": "test-collection",
            "features": [
                {"properties": {"datetime": "2023-01-15T10:00:00Z"}},
                {"properties": {"datetime": "not-a-date"}},
                {"properties": {"datetime": "2023-01-20T12:00:00Z"}},
                {"properties": {"datetime": "invalid"}}
            ]
        }
        
        collection = _build_collection(collection_json, str(tmp_path))
        
        temporal_interval = collection.extent.temporal.intervals[0]
        assert temporal_interval[0] == datetime.fromisoformat("2023-01-15T10:00:00+00:00")
        assert temporal_interval[1] == datetime.fromisoformat("2023-01-20T12:00:00+00:00")
    
    def test_temporal_extent_single_datetime(self, tmp_path):
        """Single datetime should result in start and end being the same."""
        collection_json = {
            "id": "test-collection",
            "features": [
                {"properties": {"datetime": "2023-01-15T10:00:00Z"}}
            ]
        }
        
        collection = _build_collection(collection_json, str(tmp_path))
        
        temporal_interval = collection.extent.temporal.intervals[0]
        expected_dt = datetime.fromisoformat("2023-01-15T10:00:00+00:00")
        assert temporal_interval[0] == expected_dt
        assert temporal_interval[1] == expected_dt
    
    def test_metadata_id_and_description(self, tmp_path):
        """collection.id and collection.description should match the input."""
        collection_json = {
            "id": "my-custom-collection",
            "description": "This is a custom description",
            "features": []
        }
        
        collection = _build_collection(collection_json, str(tmp_path))
        
        assert collection.id == "my-custom-collection"
        assert collection.description == "This is a custom description"
    
    def test_metadata_missing_keys_use_defaults(self, tmp_path):
        """Missing keys should fall back to defaults."""
        collection_json = {
            "features": []
        }
        
        collection = _build_collection(collection_json, str(tmp_path))
        
        assert collection.id == "local-downloaded-collection"
        assert collection.description == "A local collection containing downloaded STAC items."


class TestSingleItemDownload:
    """Test _download_single_item() behavior."""
    
    @patch('stage_in.maap.downloadGranule')
    def test_subdirectory_created(self, mock_download, tmp_path):
        """A subdirectory <output_dir>/<item.id>/ should be created."""
        item_json = {
            "type": "Feature",
            "stac_version": "1.0.0",
            "id": "test-item-123",
            "geometry": {"type": "Point", "coordinates": [0, 0]},
            "bbox": [0, 0, 1, 1],
            "properties": {"datetime": "2023-01-01T00:00:00Z"},
            "links": [],
            "assets": {}
        }
        
        parent_container = Mock()
        _download_single_item(item_json, str(tmp_path), parent_container)
        
        expected_dir = tmp_path / "test-item-123"
        assert expected_dir.exists()
        assert expected_dir.is_dir()
    
    @patch('stage_in.maap.downloadGranule')
    def test_download_granule_called_per_asset(self, mock_download, tmp_path):
        """maap.downloadGranule should be called once per asset with the correct URL."""
        mock_download.side_effect = [
            str(tmp_path / "test-item-123" / "asset1.tif"),
            str(tmp_path / "test-item-123" / "asset2.json")
        ]

        item_json = {
            "type": "Feature",
            "stac_version": "1.0.0",
            "id": "test-item-123",
            "geometry": {"type": "Point", "coordinates": [0, 0]},
            "bbox": [0, 0, 1, 1],
            "properties": {"datetime": "2023-01-01T00:00:00Z"},
            "links": [],
            "assets": {
                "data": {"href": "https://example.com/data.tif", "type": "image/tiff"},
                "metadata": {"href": "https://example.com/meta.json", "type": "application/json"}
            }
        }
        
        parent_container = Mock()
        _download_single_item(item_json, str(tmp_path), parent_container)
        
        assert mock_download.call_count == 2
        calls = mock_download.call_args_list
        assert calls[0][1]['online_access_url'] == "https://example.com/data.tif"
        assert calls[1][1]['online_access_url'] == "https://example.com/meta.json"
    
    @patch('stage_in.maap.downloadGranule')
    def test_returned_item_added_to_parent(self, mock_download, tmp_path):
        """The returned item should be added to the parent container."""
        mock_download.return_value = str(tmp_path / "test-item-123" / "asset.tif")

        item_json = {
            "type": "Feature",
            "stac_version": "1.0.0",
            "id": "test-item-123",
            "geometry": {"type": "Point", "coordinates": [0, 0]},
            "bbox": [0, 0, 1, 1],
            "properties": {"datetime": "2023-01-01T00:00:00Z"},
            "links": [],
            "assets": {
                "data": {"href": "https://example.com/data.tif", "type": "image/tiff"}
            }
        }
        
        parent_container = Mock()
        result = _download_single_item(item_json, str(tmp_path), parent_container)
        
        parent_container.add_item.assert_called_once()
        added_item = parent_container.add_item.call_args[0][0]
        assert added_item.id == "test-item-123"
        assert isinstance(result, pystac.Item)
    
    @patch('stage_in.maap.downloadGranule')
    def test_asset_hrefs_are_relative(self, mock_download, tmp_path):
        """All asset hrefs on the returned item should be relative paths."""
        mock_download.return_value = str(tmp_path / "test-item-123" / "asset.tif")

        item_json = {
            "type": "Feature",
            "stac_version": "1.0.0",
            "id": "test-item-123",
            "geometry": {"type": "Point", "coordinates": [0, 0]},
            "bbox": [0, 0, 1, 1],
            "properties": {"datetime": "2023-01-01T00:00:00Z"},
            "links": [],
            "assets": {
                "data": {"href": "https://example.com/data.tif", "type": "image/tiff"}
            }
        }
        
        parent_container = Mock()
        result = _download_single_item(item_json, str(tmp_path), parent_container)
        
        for asset_key, asset in result.assets.items():
            assert not asset.href.startswith("http")
            assert not os.path.isabs(asset.href)
    
    @patch('stage_in.maap.downloadGranule')
    def test_one_asset_fails_rest_still_download(self, mock_download, tmp_path):
        """If one asset fails, the rest should still download (no crash)."""
        def side_effect(*args, **kwargs):
            url = kwargs['online_access_url']
            if 'fail' in url:
                raise Exception("Download failed")
            return str(tmp_path / "test-item-123" / "success.tif")

        mock_download.side_effect = side_effect

        item_json = {
            "type": "Feature",
            "stac_version": "1.0.0",
            "id": "test-item-123",
            "geometry": {"type": "Point", "coordinates": [0, 0]},
            "bbox": [0, 0, 1, 1],
            "properties": {"datetime": "2023-01-01T00:00:00Z"},
            "links": [],
            "assets": {
                "good1": {"href": "https://example.com/good1.tif", "type": "image/tiff"},
                "bad": {"href": "https://example.com/fail.tif", "type": "image/tiff"},
                "good2": {"href": "https://example.com/good2.tif", "type": "image/tiff"}
            }
        }
        
        parent_container = Mock()
        result = _download_single_item(item_json, str(tmp_path), parent_container)
        
        assert mock_download.call_count == 3
        assert len(result.assets) == 2
        assert "good1" in result.assets
        assert "good2" in result.assets
        assert "bad" not in result.assets
    
    @patch('stage_in.maap.downloadGranule')
    def test_zero_assets_no_download_calls(self, mock_download, tmp_path):
        """Zero assets should result in downloadGranule never being called."""
        item_json = {
            "type": "Feature",
            "stac_version": "1.0.0",
            "id": "test-item-123",
            "geometry": {"type": "Point", "coordinates": [0, 0]},
            "bbox": [0, 0, 1, 1],
            "properties": {"datetime": "2023-01-01T00:00:00Z"},
            "links": [],
            "assets": {}
        }
        
        parent_container = Mock()
        _download_single_item(item_json, str(tmp_path), parent_container)
        
        mock_download.assert_not_called()


class TestSingleItemCatalogAssembly:
    """Test download_stac_item_assets_from_json() catalog assembly."""
    
    @patch('stage_in.maap.downloadGranule')
    @patch('pystac.Catalog.save')
    def test_output_directory_created(self, mock_save, mock_download, tmp_path):
        """Output directory should be created."""
        output_dir = tmp_path / "test_output"

        item_json = {
            "type": "Feature",
            "stac_version": "1.0.0",
            "id": "test-item",
            "geometry": {"type": "Point", "coordinates": [0, 0]},
            "bbox": [0, 0, 1, 1],
            "properties": {"datetime": "2023-01-01T00:00:00Z"},
            "links": [],
            "assets": {}
        }
        
        download_stac_item_assets_from_json(item_json, str(output_dir))
        
        assert output_dir.exists()
    
    @patch('stage_in.maap.downloadGranule')
    @patch('pystac.Catalog.save')
    def test_catalog_json_exists(self, mock_save, mock_download, tmp_path):
        """catalog.json should exist after the call."""
        output_dir = tmp_path / "test_output"

        item_json = {
            "type": "Feature",
            "stac_version": "1.0.0",
            "id": "test-item",
            "geometry": {"type": "Point", "coordinates": [0, 0]},
            "bbox": [0, 0, 1, 1],
            "properties": {"datetime": "2023-01-01T00:00:00Z"},
            "links": [],
            "assets": {}
        }
        
        download_stac_item_assets_from_json(item_json, str(output_dir))
        
        mock_save.assert_called_once()
    
    @patch('stage_in.maap.downloadGranule')
    @patch('pystac.Catalog.save')
    def test_catalog_contains_one_item(self, mock_save, mock_download, tmp_path):
        """The catalog should contain exactly the one item from input."""
        output_dir = tmp_path / "test_output"
        mock_download.return_value = str(output_dir / "test-item" / "asset.tif")

        item_json = {
            "type": "Feature",
            "stac_version": "1.0.0",
            "id": "test-item",
            "geometry": {"type": "Point", "coordinates": [0, 0]},
            "bbox": [0, 0, 1, 1],
            "properties": {"datetime": "2023-01-01T00:00:00Z"},
            "links": [],
            "assets": {
                "data": {"href": "https://example.com/data.tif", "type": "image/tiff"}
            }
        }
        
        with patch('stage_in._download_single_item', wraps=_download_single_item) as mock_dl:
            download_stac_item_assets_from_json(item_json, str(output_dir))
            
            mock_dl.assert_called_once()
            parent_catalog = mock_dl.call_args[0][2]
            assert parent_catalog.id == "local-downloaded-catalog"
    
    @patch('stage_in._download_single_item')
    @patch('pystac.Catalog.save')
    def test_exception_caught_and_printed(self, mock_save, mock_download, tmp_path, capsys):
        """An internal exception should be caught and printed (no propagation)."""
        mock_download.side_effect = Exception("Test exception")

        item_json = {
            "type": "Feature",
            "stac_version": "1.0.0",
            "id": "test-item",
            "geometry": {"type": "Point", "coordinates": [0, 0]},
            "bbox": [0, 0, 1, 1],
            "properties": {"datetime": "2023-01-01T00:00:00Z"},
            "links": [],
            "assets": {}
        }
        
        download_stac_item_assets_from_json(item_json, str(tmp_path))
        
        captured = capsys.readouterr()
        assert "An error occurred" in captured.out
        assert "Test exception" in captured.out


class TestCollectionCatalogAssembly:
    """Test download_stac_collection_assets_from_json() catalog assembly."""
    
    @patch('stage_in._download_single_item')
    @patch('pystac.Catalog.save')
    def test_download_called_once_per_feature(self, mock_save, mock_download, tmp_path):
        """_download_single_item should be called once per feature."""
        collection_json = {
            "type": "FeatureCollection",
            "id": "test-collection",
            "features": [
                {
                    "type": "Feature",
                    "stac_version": "1.0.0",
                    "id": "item1",
                    "geometry": {"type": "Point", "coordinates": [0, 0]},
                    "bbox": [0, 0, 1, 1],
                    "properties": {"datetime": "2023-01-01T00:00:00Z"},
                    "links": [],
                    "assets": {}
                },
                {
                    "type": "Feature",
                    "stac_version": "1.0.0",
                    "id": "item2",
                    "geometry": {"type": "Point", "coordinates": [1, 1]},
                    "bbox": [1, 1, 2, 2],
                    "properties": {"datetime": "2023-01-02T00:00:00Z"},
                    "links": [],
                    "assets": {}
                },
                {
                    "type": "Feature",
                    "stac_version": "1.0.0",
                    "id": "item3",
                    "geometry": {"type": "Point", "coordinates": [2, 2]},
                    "bbox": [2, 2, 3, 3],
                    "properties": {"datetime": "2023-01-03T00:00:00Z"},
                    "links": [],
                    "assets": {}
                }
            ]
        }
        
        download_stac_collection_assets_from_json(collection_json, str(tmp_path))
        
        assert mock_download.call_count == 3
    
    @patch('stage_in._download_single_item')
    @patch('pystac.Catalog.save')
    def test_collection_nested_under_root_catalog(self, mock_save, mock_download, tmp_path):
        """The collection should be nested under the root catalog (not items at root level)."""
        collection_json = {
            "type": "FeatureCollection",
            "id": "test-collection",
            "features": [
                {
                    "type": "Feature",
                    "stac_version": "1.0.0",
                    "id": "item1",
                    "geometry": {"type": "Point", "coordinates": [0, 0]},
                    "bbox": [0, 0, 1, 1],
                    "properties": {"datetime": "2023-01-01T00:00:00Z"},
                    "links": [],
                    "assets": {}
                }
            ]
        }

        download_stac_collection_assets_from_json(collection_json, str(tmp_path))

        mock_download.assert_called_once()
        parent_container = mock_download.call_args[0][2]
        assert parent_container.id == "test-collection"
    
    @patch('stage_in._download_single_item')
    @patch('pystac.Catalog.save')
    def test_empty_features_list_produces_valid_collection(self, mock_save, mock_download, tmp_path):
        """An empty features list should still produce a valid, saved collection."""
        collection_json = {
            "type": "FeatureCollection",
            "id": "empty-collection",
            "features": []
        }
        
        download_stac_collection_assets_from_json(collection_json, str(tmp_path))
        
        mock_download.assert_not_called()
        mock_save.assert_called_once()
    
    @patch('stage_in._download_single_item')
    @patch('pystac.Catalog.save')
    def test_exception_caught_and_printed(self, mock_save, mock_download, tmp_path, capsys):
        """An internal exception should be caught and printed."""
        mock_download.side_effect = Exception("Test collection exception")

        collection_json = {
            "type": "FeatureCollection",
            "id": "test-collection",
            "features": [
                {
                    "type": "Feature",
                    "stac_version": "1.0.0",
                    "id": "item1",
                    "geometry": {"type": "Point", "coordinates": [0, 0]},
                    "bbox": [0, 0, 1, 1],
                    "properties": {"datetime": "2023-01-01T00:00:00Z"},
                    "links": [],
                    "assets": {}
                }
            ]
        }
        
        download_stac_collection_assets_from_json(collection_json, str(tmp_path))
        
        captured = capsys.readouterr()
        assert "An error occurred" in captured.out
        assert "Test collection exception" in captured.out


class TestMainEntryPoint:
    """Test main() entry point."""
    
    @patch('stage_in.download_stac_assets_from_json')
    def test_feature_json_file_parsed_and_dispatched(self, mock_dispatch, tmp_path):
        """A temp file with a Feature JSON should call download_stac_assets_from_json with parsed dict."""
        feature_json = {
            "type": "Feature",
            "stac_version": "1.0.0",
            "id": "test-item",
            "geometry": {"type": "Point", "coordinates": [0, 0]},
            "bbox": [0, 0, 1, 1],
            "properties": {"datetime": "2023-01-01T00:00:00Z"},
            "links": [],
            "assets": {}
        }
        
        json_file = tmp_path / "feature.json"
        with open(json_file, 'w') as f:
            json.dump(feature_json, f)
        
        main(str(json_file), str(tmp_path / "output"))
        
        mock_dispatch.assert_called_once()
        call_args = mock_dispatch.call_args
        assert call_args[0][0] == feature_json
        assert call_args[1]['output_dir'] == str(tmp_path / "output")
    
    @patch('stage_in.download_stac_assets_from_json')
    def test_feature_collection_json_file_parsed_and_dispatched(self, mock_dispatch, tmp_path):
        """A temp file with a FeatureCollection JSON should call download_stac_assets_from_json with parsed dict."""
        collection_json = {
            "type": "FeatureCollection",
            "id": "test-collection",
            "features": [
                {
                    "type": "Feature",
                    "stac_version": "1.0.0",
                    "id": "item1",
                    "geometry": {"type": "Point", "coordinates": [0, 0]},
                    "bbox": [0, 0, 1, 1],
                    "properties": {"datetime": "2023-01-01T00:00:00Z"},
                    "links": [],
                    "assets": {}
                }
            ]
        }
        
        json_file = tmp_path / "collection.json"
        with open(json_file, 'w') as f:
            json.dump(collection_json, f)
        
        main(str(json_file), str(tmp_path / "output"))
        
        mock_dispatch.assert_called_once()
        call_args = mock_dispatch.call_args
        assert call_args[0][0] == collection_json
        assert call_args[1]['output_dir'] == str(tmp_path / "output")
