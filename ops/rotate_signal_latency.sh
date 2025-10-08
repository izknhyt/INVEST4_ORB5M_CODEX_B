#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CSV_PATH="${SCRIPT_DIR}/signal_latency.csv"
ARCHIVE_DIR="${SCRIPT_DIR}/archive"

mkdir -p "${ARCHIVE_DIR}"

if [[ ! -f "${CSV_PATH}" ]]; then
  printf 'signal_id,ts_emit,ts_ack,status,detail\n' > "${CSV_PATH}"
  printf 'Initialized %s with default header\n' "${CSV_PATH}"
  exit 0
fi

timestamp="$(date -u +"%Y%m%dT%H%M%SZ")"
archive_path="${ARCHIVE_DIR}/signal_latency_${timestamp}.csv"

mv "${CSV_PATH}" "${archive_path}"
header_line="$(head -n 1 "${archive_path}" 2>/dev/null || printf 'signal_id,ts_emit,ts_ack,status,detail')"
printf '%s\n' "${header_line}" > "${CSV_PATH}"

printf 'Rotated %s to %s\n' "${CSV_PATH}" "${archive_path}"
