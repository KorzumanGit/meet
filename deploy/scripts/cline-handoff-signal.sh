#!/usr/bin/env bash
# 脳（Cursor）→手足（Cline）への「実行開始」信号（ファイルベース）。
# 先頭行 SIGNAL: START_GCP_DEPLOYMENT を Cline が検知できるようにする。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
STAMP="$ROOT/.cline_handoff_requested"
TS="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

{
  echo "SIGNAL: START_GCP_DEPLOYMENT"
  echo "$TS  Cursor→Cline 全権委譲・実行開始"
  echo "repo=$ROOT"
  echo "read_first=deploy/CLINE_START_HERE.txt"
} >"$STAMP"

echo "=== CLINE_HANDOFF ==="
echo "Signal written: $STAMP"
echo "Cline: read $ROOT/deploy/CLINE_START_HERE.txt then deploy/CLINE_FINAL_PROMPT.txt"
echo "====================="
