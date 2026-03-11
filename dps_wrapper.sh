#!/bin/bash

USERNAME=$(python /app/get_username.py)
source /maap-dps.env
export MAAP_API_HOST
export DPS_MACHINE_TOKEN
MAAP_PGT=$(python /app/get_maap_pgt_token.py)
export MAAP_PGT
unset DPS_MACHINE_TOKEN

mkdir -p input
set -ex
CWL_FILE=$1
aws s3 cp "$CWL_FILE" .
CWL_FILE=$(basename "$CWL_FILE")
# Create inputs.yml from hysds context for input to cwltool command
python /app/create_inputs.py $CWL_FILE

cwltool --disable-color --no-read-only --preserve-environment MAAP_PGT --preserve-environment MAAP_API_HOST \
        --cidfile-dir $PWD --tmpdir-prefix $PWD --log-dir ${PWD} \
        --write-summary ${PWD}/cwl_summary.json \
        ${CWL_FILE} inputs.yml || (tail -n 20 _stderr.txt > _alt_traceback.txt && exit 1)

# Stage out: discover all CWL outputs with metadata
echo "=== Starting Stage Out Process ==="
python /app/stage_out.py ${CWL_FILE} --json-output --cwl-summary ${PWD}/cwl_summary.json > /tmp/stage_out_result.json

# Process outputs using Python to handle multiple outputs
python /app/process_outputs.py /tmp/stage_out_result.json

