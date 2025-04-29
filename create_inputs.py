import json
import pathlib

import yaml
import os
import argparse
import sys
from cwl_utils.parser import load_document_by_uri
from cwl_utils.parser.cwl_v1_2 import CommandLineTool, CommandInputParameter
import urllib.parse
import stage_in


def get_id_from_uri(uri):
    fragment = urllib.parse.urlparse(uri).fragment
    return os.path.basename(fragment)


def parse_cwl_inputs(cwl_file_path) -> [CommandInputParameter]:
    """
    Loads a CWL file, checks if it's a CommandLineTool,
    and prints the IDs of its input parameters.

    Args:
        cwl_file_path (str): The path or URI to the CWL file.

    Returns:
        List of CommandInputParameter
    """
    print(f"Attempting to parse CWL file: {cwl_file_path}")
    try:
        # Load the CWL document using the provided path/URI
        # The 'file://' prefix is often needed for local files
        uri = f"file://{cwl_file_path}" if not cwl_file_path.startswith("file://") else cwl_file_path
        cwl_object = load_document_by_uri(uri)

        # Check if the loaded object is a CommandLineTool
        if isinstance(cwl_object, CommandLineTool):
            print("\nSuccessfully parsed CommandLineTool.")
            print("Inputs required by this tool:")

            if not cwl_object.inputs:
                print("- No inputs defined.")
                return

            return cwl_object.inputs

        else:
            # Handle cases where the file is a valid CWL document but not a CommandLineTool
            print(f"\nError: The CWL document '{cwl_file_path}' is not a CommandLineTool.")
            print(f"It is of type: {type(cwl_object).__name__}")
            sys.exit(1)  # Exit with an error code

    except FileNotFoundError:
        print(f"\nError: The file '{cwl_file_path}' was not found.")
        sys.exit(1)
    except Exception as e:
        # Catch any other unexpected errors during loading/parsing
        print(f"\nAn unexpected error occurred:")
        print(e)
        sys.exit(1)


def get_inputs_from_context():
    """
    Parses the _context.json file and returns the user provided inputs
    :return: a dictionary of cwl key and user provided value
    """
    with open("_context.json", "r") as f:
        try:
            job_context = json.loads(f.read())
        except json.decoder.JSONDecodeError:
            print("File is empty")

    # print(f"job_context: {json.dumps(job_context, indent=2)}")
    workflow_inputs = dict()
    job_params = job_context.get("job_specification").get("params")
    for param in job_params:
        workflow_inputs[param.get("name")] = str(param.get("value"))
    return workflow_inputs


def map_inputs_from_context(job_inputs: dict, cwl_inputs: [CommandInputParameter]):
    workflow_inputs = dict()
    for input in cwl_inputs:
        input_type = input.type_
        input_name = get_id_from_uri(input.id)
        if input_type == "Directory":
            print("Encountered STAC input, localizing assets.")
            # STAC Item json is assumed to have been downloaded by hysds
            stac_item_file = os.path.basename(job_inputs.get(input_name))
            stac_item_json = json.load(open(stac_item_file, "r"))
            output_dir = str(pathlib.Path(input_name).resolve())
            stage_in.download_stac_item_assets_from_json(stac_item_json, output_dir)
            workflow_inputs[input_name] = {"class": "Directory", "path": output_dir}
        elif input_type == "File":
            filepath = pathlib.Path(os.path.basename(job_inputs.get(input_name)))
            workflow_inputs[input_name] = {"class": "File", "path": str(filepath.resolve())}
        else:
            workflow_inputs[input_name] = job_inputs.get(input_name)
    return workflow_inputs


def create_input_yml(workflow_inputs: dict):
    # write out yaml
    with open(r"inputs.yml", "w") as file:
        yaml.dump(workflow_inputs, file)
    print(yaml.dump(workflow_inputs))


def main(cwl_file_path):
    """

    :param cwl_file_path:
    :return:
    """
    cwl_inputs = parse_cwl_inputs(cwl_file_path)
    job_inputs = get_inputs_from_context()
    workflow_inputs = map_inputs_from_context(job_inputs, cwl_inputs)
    create_input_yml(workflow_inputs)


if __name__ == "__main__":
    # Set up argument parser
    parser = argparse.ArgumentParser(
        description="Parse a CWL CommandLineTool file and list its inputs."
    )
    parser.add_argument(
        "cwl_file",
        help="Path to the CWL CommandLineTool file (.cwl)."
    )

    # Parse the command-line arguments
    args = parser.parse_args()

    # Call the main function with the provided file path
    main(cwl_file_path=args.cwl_file)
