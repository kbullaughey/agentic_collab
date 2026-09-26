#!/bin/bash

BACKEND_SCRIPT_PATH="reverie/backend_server"
BACKEND_SCRIPT_FILE="automatic_execution.py"
LOGS_PATH="../../logs"

FILE_NAME="Bash-Script"
cd ${BACKEND_SCRIPT_PATH}


ARGS=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --origin|-o)
            ARGS="${ARGS} --origin ${2}"
            shift 2
            ;;
        --target|-t)
            ARGS="${ARGS} --target ${2}"
            TARGET=${2}
            shift 2
            ;;
        --steps|-s)
            ARGS="${ARGS} --steps ${2}"
            shift 2
            ;;
        --ui)
            ARGS="${ARGS} --ui ${2}"
            shift 2
            ;;
        --browser_path|-bp)
            ARGS="${ARGS} --browser_path ${2}"
            shift 2
            ;;
        --port|-p)
            ARGS="${ARGS} --port ${2}"
            echo "(${FILE_NAME}): Running backend server at: http://127.0.0.1:${2}/simulator_home"
            shift 2
            ;;
        --load_history|-h)
            ARGS="${ARGS} --load_history ${2}"
            shift 2
            ;;
        --mqtt)
            ARGS="${ARGS} --mqtt"
            echo "(${FILE_NAME}): MQTT mode enabled"
            shift
            ;;
        *)
            echo "Unknown argument: $1"
            exit 1
            ;;
    esac
done

set -- "${POSITIONAL_ARGS[@]}" # restore positional parameters
echo "(${FILE_NAME}): Arguments: ${ARGS}"

timestamp=$(date +"%Y-%m-%d_%H-%M-%S")
echo "(${FILE_NAME}): Timestamp: ${timestamp}"
mkdir -p ${LOGS_PATH}
uv run python ${BACKEND_SCRIPT_FILE} ${ARGS} 2>&1 | tee ${LOGS_PATH}/${TARGET}_${timestamp}.txt
