import pytest
import sys
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

# Add parent directory to path to import create_inputs
sys.path.insert(0, str(Path(__file__).parent.parent))

from create_inputs import map_inputs_from_context


def _cwl_input(name, type_):
    """Build a minimal stand-in for a cwl_utils CommandInputParameter."""
    return Mock(id=f"file:///process.cwl#main/{name}", type_=type_)


class TestOptionalFileDirectoryInputs:
    """Test handling of empty File/Directory inputs in map_inputs_from_context()."""

    @pytest.mark.parametrize("type_", [["null", "File"], "File?"])
    @pytest.mark.parametrize("value", [None, "", "None"])
    def test_empty_optional_file_is_omitted(self, type_, value):
        cwl_inputs = [_cwl_input("opt_file", type_)]
        job_inputs = {} if value is None else {"opt_file": value}

        assert map_inputs_from_context(job_inputs, cwl_inputs) == {}

    @pytest.mark.parametrize("type_", [["null", "Directory"], "Directory?"])
    @pytest.mark.parametrize("value", [None, "", "None"])
    @patch('create_inputs.stage_in.download_stac_assets_from_json')
    @patch('create_inputs.load_json_from_uri')
    def test_empty_optional_directory_is_omitted_without_staging(self, mock_load, mock_download, type_, value):
        cwl_inputs = [_cwl_input("opt_dir", type_)]
        job_inputs = {} if value is None else {"opt_dir": value}

        assert map_inputs_from_context(job_inputs, cwl_inputs) == {}
        mock_load.assert_not_called()
        mock_download.assert_not_called()

    @pytest.mark.parametrize("type_", ["File", "Directory"])
    @pytest.mark.parametrize("value", [None, ""])
    def test_empty_required_file_or_directory_raises(self, type_, value):
        cwl_inputs = [_cwl_input("req_input", type_)]
        job_inputs = {} if value is None else {"req_input": value}

        with pytest.raises(ValueError, match="req_input"):
            map_inputs_from_context(job_inputs, cwl_inputs)

    def test_provided_optional_file_is_included(self):
        cwl_inputs = [_cwl_input("opt_file", ["null", "File"])]
        job_inputs = {"opt_file": "s3://bucket/path/data.tif"}

        result = map_inputs_from_context(job_inputs, cwl_inputs)

        assert result["opt_file"]["class"] == "File"
        assert result["opt_file"]["path"] == str(Path("data.tif").resolve())

    @patch('create_inputs.stage_in.download_stac_assets_from_json')
    @patch('create_inputs.load_json_from_uri', return_value={"type": "Feature"})
    def test_provided_optional_directory_is_staged(self, mock_load, mock_download):
        cwl_inputs = [_cwl_input("opt_dir", ["null", "Directory"])]
        job_inputs = {"opt_dir": "https://example.com/item.json"}

        result = map_inputs_from_context(job_inputs, cwl_inputs)

        mock_load.assert_called_once_with("https://example.com/item.json")
        mock_download.assert_called_once()
        assert result["opt_dir"] == {"class": "Directory", "path": str(Path("opt_dir").resolve())}

    def test_empty_optional_file_does_not_affect_other_inputs(self):
        cwl_inputs = [
            _cwl_input("opt_file", ["null", "File"]),
            _cwl_input("req_str", "string"),
            _cwl_input("opt_str", ["null", "string"]),
        ]
        job_inputs = {"req_str": "x", "opt_str": ""}

        assert map_inputs_from_context(job_inputs, cwl_inputs) == {"req_str": "x"}


class TestLoadJsonFromUriRetry:
    @patch('create_inputs.time.sleep')
    @patch('create_inputs.requests.get')
    def test_retries_transient_503_then_succeeds(self, mock_get, _sleep):
        import requests
        import create_inputs
        bad = MagicMock()
        bad.raise_for_status.side_effect = requests.exceptions.HTTPError("503")
        good = MagicMock()
        good.json.return_value = {"type": "Feature"}
        mock_get.side_effect = [bad, bad, good]
        assert create_inputs.load_json_from_uri("https://example.com/item") == {"type": "Feature"}
        assert mock_get.call_count == 3

    @patch('create_inputs.time.sleep')
    @patch('create_inputs.requests.get')
    def test_returns_none_after_exhausting_retries(self, mock_get, _sleep):
        import requests
        import create_inputs
        mock_get.side_effect = requests.exceptions.ConnectionError("down")
        assert create_inputs.load_json_from_uri("https://example.com/item") is None
        assert mock_get.call_count == create_inputs.HTTP_RETRIES
