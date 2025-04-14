import sys
import json
import os

if __name__ == '__main__':
    with open("_job.json") as fr:
        job = json.loads(fr.read())
        print(job.get("username", "null"))