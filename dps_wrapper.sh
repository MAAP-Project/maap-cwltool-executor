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

cwltool --no-read-only --no-match-user --preserve-environment MAAP_PGT \
        --cidfile-dir $PWD --tmpdir-prefix $PWD --log-dir ${PWD} \
        ${CWL_FILE} inputs.yml || (cp _stderr.txt _alt_traceback.txt && exit 1)

USER_OUTPUT_DIR="output"

DIRNAME=$(date +"%Y-%m-%dT%H:%M:%S.%6N")
DATASET_NAME="output-$DIRNAME"

if [ ! -d ${USER_OUTPUT_DIR} ]; then
    mkdir -p ${USER_OUTPUT_DIR}
fi

cp -v _std* ${USER_OUTPUT_DIR}/

mv ${USER_OUTPUT_DIR} ${DATASET_NAME}

python /app/dps_wrapper.py ${DATASET_NAME}

