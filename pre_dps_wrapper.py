import json
import shutil
import os


cwd = os.getcwd()
with open(os.path.join(cwd, "_context.json"), "r") as fr:
    context = json.load(fr)
    for url in context.get("localize_urls", []):
        file = url.get("url")
        file = os.path.basename(file)
        shutil.move(os.path.join(cwd, file), os.path.join(cwd, "input", file))
