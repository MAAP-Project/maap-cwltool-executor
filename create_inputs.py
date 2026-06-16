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
import requests
import boto3
from botocore.exceptions import BotoCoreError, ClientError


def get_id_from_uri(uri):
    fragment = urllib.parse.urlparse(uri).fragment
    return os.path.basename(fragment)


def parse_cwl_type(cwl_type):
    """
    Parse CWL type definition and return base type and optional flag.

    The cwl_utils library may represent types as:
    - Strings: "int", "boolean", "string", "File", "Directory"
    - Lists for optional: ["null", "int"] or ["int", "null"]
    - Type objects

    Args:
        cwl_type: Type definition from cwl_utils

    Returns:
        tuple: (base_type: str, is_optional: bool)
    """
    # Handle list type (e.g., ["null", "int"])
    if isinstance(cwl_type, list):
        # Filter out "null" to get the actual type
        types = [t for t in cwl_type if t != "null"]
        is_optional = len(cwl_type) != len(types)
        base_type = types[0] if types else "null"
        return (base_type, is_optional)

    # Handle string type
    if isinstance(cwl_type, str):
        # Check for optional suffix
        if cwl_type.endswith("?"):
            return (cwl_type[:-1], True)
        else:
            return (cwl_type, False)

    # Handle type objects by converting to string
    return (str(cwl_type), False)


def convert_value_to_cwl_type(value, cwl_type_str):
    """
    Convert a value to the appropriate Python type based on CWL type.

    Args:
        value: The value to convert (from job context)
        cwl_type_str: The CWL type string (e.g., "int?", "boolean", "string")

    Returns:
        Properly typed value or None for omitted optional values
    """
    base_type, is_optional = parse_cwl_type(cwl_type_str)

    # Handle None/null values for optional types
    if value is None or value == "None" or value == "":
        return None if is_optional else value

    # Convert to appropriate type
    if base_type in ("int", "integer"):
        try:
            return int(value)
        except (ValueError, TypeError):
            return None if is_optional else value

    elif base_type in ("boolean", "bool"):
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ("true", "1", "yes")
        return bool(value)

    elif base_type in ("string", "str"):
        return str(value)

    else:
        # For other types (File, Directory, etc.), pass through
        return value


def load_json_from_uri(uri):
    parsed = urllib.parse.urlparse(uri)

    if parsed.scheme == "s3":
        bucket = parsed.netloc
        key = parsed.path.lstrip("/")
        try:
            s3 = boto3.client("s3")
            response = s3.get_object(Bucket=bucket, Key=key)
            return json.loads(response["Body"].read())
        except (BotoCoreError, ClientError) as e:
            print(f"S3 error: {e}")
            return None
        except ValueError as e:
            print(f"Failed to parse JSON: {e}")
            return None

    # http / https
    try:
        response = requests.get(uri)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Request error: {e}")
        return None
    except ValueError as e:
        print(f"Failed to parse JSON: {e}")
        return None


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
        uri = str(pathlib.Path(cwl_file_path).resolve().as_uri()) if not cwl_file_path.startswith("file://") else cwl_file_path
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
        # Keep original value type (don't convert to string)
        workflow_inputs[param.get("name")] = param.get("value")
    return workflow_inputs


def map_inputs_from_context(job_inputs: dict, cwl_inputs: [CommandInputParameter]):
    workflow_inputs = dict()
    for input in cwl_inputs:
        input_type = input.type_
        input_name = get_id_from_uri(input.id)
        base_type, is_optional = parse_cwl_type(input_type)

        if base_type == "Directory":
            print("Encountered STAC input, localizing assets.")
            # Load STAC JSON directly from the URI rather than using the HySDS-localized copy.
            # HySDS caches localized files by URI path — if the JSON content changes at the same
            # URI, HySDS serves the stale cached version. Fetching from the URI at runtime
            # guarantees we always get the current content.
            # TODO: Update the HySDS spec builder to not map this input as a localize field.
            stac_json = load_json_from_uri(job_inputs.get(input_name))
            output_dir = str(pathlib.Path(input_name).resolve())
            stage_in.download_stac_assets_from_json(stac_json, output_dir)
            workflow_inputs[input_name] = {"class": "Directory", "path": output_dir}
        elif base_type == "File":
            filepath = pathlib.Path(os.path.basename(job_inputs.get(input_name)))
            workflow_inputs[input_name] = {"class": "File", "path": str(filepath.resolve())}
        else:
            # For primitive types (int, boolean, string, etc.)
            raw_value = job_inputs.get(input_name)
            converted_value = convert_value_to_cwl_type(raw_value, input_type)

            # Only include in output if value is not None
            # (optional parameters with no value can be omitted)
            if converted_value is not None:
                workflow_inputs[input_name] = converted_value
            elif not is_optional:
                # Required parameters should be included even if None
                workflow_inputs[input_name] = converted_value

    return workflow_inputs


def create_input_yml(workflow_inputs: dict):
    # Filter out None values for optional parameters
    filtered_inputs = {k: v for k, v in workflow_inputs.items() if v is not None}

    # write out yaml
    with open(r"inputs.yml", "w") as file:
        yaml.dump(filtered_inputs, file, default_flow_style=False)
    print(yaml.dump(filtered_inputs, default_flow_style=False))


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
