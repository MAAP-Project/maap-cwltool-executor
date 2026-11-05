import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from create_inputs import map_inputs_from_context, parse_cwl_inputs

NO_INPUTS_CWL = """\
cwlVersion: v1.2
class: CommandLineTool
baseCommand: [sh, -c, "mkdir -p output && echo hi > output/out.txt"]
inputs: []
outputs: []
"""


def test_parse_cwl_inputs_returns_empty_list_when_no_inputs(tmp_path):
    cwl = tmp_path / "no-inputs.cwl"
    cwl.write_text(NO_INPUTS_CWL)

    assert parse_cwl_inputs(str(cwl)) == []


def test_no_input_cwl_maps_to_empty_workflow_inputs(tmp_path):
    cwl = tmp_path / "no-inputs.cwl"
    cwl.write_text(NO_INPUTS_CWL)

    cwl_inputs = parse_cwl_inputs(str(cwl))

    assert map_inputs_from_context({}, cwl_inputs) == {}
