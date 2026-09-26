#!/bin/bash

BACKEND_SCRIPT_PATH="reverie/backend_server"
BACKEND_SCRIPT_FILE="reverie.py"
LOGS_PATH="../../logs"

cd ${BACKEND_SCRIPT_PATH}

echo "Running backend server at: http://127.0.0.1:8000/simulator_home"
timestamp=$(date +"%Y-%m-%d_%H-%M-%S")
echo "Timestamp: ${timestamp}"
mkdir -p ${LOGS_PATH}
uv run python ${BACKEND_SCRIPT_FILE} --origin ${1} --target ${2} 2>&1 | tee ${LOGS_PATH}/${2}_${timestamp}.txt
