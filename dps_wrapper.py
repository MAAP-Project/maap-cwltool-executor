import sys
import json
import os


def get_info_from_job():
    with open("_job.json") as fr:
        job = json.loads(fr.read())
        username = job.get("username", "null")
        job_type_info = str(job.get("type")).split(":")  # example job-s1_orbit_crawler:release-20190313
        algo_name = job_type_info[0].replace("job-", "")
        algo_version = job_type_info[1]
        tag = job.get("tag", "null-tag")
        return {"username": username, "algorithm_name": algo_name, "algorithm_version": algo_version, "tag": tag}


def generate_dataset_file(dataset_name):
    datasets_file_name = "{}.dataset.json".format(dataset_name)
    with open(os.path.join(dataset_name, datasets_file_name), 'w') as fw:
        fw.write(json.dumps({"version": "v1.0"}))


def generate_met_file(dataset_name):
    met_file_name = "{}.met.json".format(dataset_name)
    with open(os.path.join(dataset_name, met_file_name), 'w') as fw:
        fw.write(json.dumps(get_info_from_job()))


if __name__ == '__main__':
    dataset_name = sys.argv[1]
    generate_dataset_file(dataset_name)
    generate_met_file(dataset_name)

