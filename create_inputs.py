#!/usr/bin/env python
import json
import yaml
import os


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
        if param.get("destination") == "localize":
            file_dir_name = param.get("value").split('/')[-1].strip()
            print(file_dir_name)
            file_dir_path = os.path.join(os.getcwd(), file_dir_name)
            if os.path.isdir(file_dir_path):
                workflow_inputs[param.get("name")] = {"class": "Directory", "path": file_dir_path}
            elif os.path.isfile(file_dir_path):
                workflow_inputs[param.get("name")] = {"class": "File", "path": file_dir_path}
            else:
                raise Exception("Path does not exists : {}".format(file_dir_path))

        else:
            workflow_inputs[param.get("name")] = str(param.get("value"))
    return workflow_inputs


def create_input_yml():
    # Reading in job inputs
    wfl_inps = get_inputs_from_context()

    # write out yaml
    with open(r"inputs.yml", "w") as file:
        yaml.dump(wfl_inps, file)
    print(yaml.dump(wfl_inps))


if __name__ == "__main__":
    create_input_yml()
