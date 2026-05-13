import json
import os
import requests


def get_maap_pgt_token(username, maap_api_host=os.environ.get("MAAP_API_HOST")):
    url = f"https://{maap_api_host}/api/members/{username}"
    headers = {"dps-token": os.environ.get("DPS_MACHINE_TOKEN")}
    response = requests.get(url, headers=headers)
    maap_pgt_token = response.json()["session_key"]
    return maap_pgt_token


if __name__ == '__main__':
    with open("_job.json") as fr:
        job = json.loads(fr.read())
        username = job.get("username")
        if username:
            try:
                maap_pgt_token = get_maap_pgt_token(username)
                print(maap_pgt_token)
            except Exception as e:
                print(f"Unable to get user MAAP_PGT token: {e}")
                raise e
