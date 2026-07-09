#!/bin/bash
set -euo pipefail

echo "Starting EDA (Enhanced Dynamic Activation) VNE"
echo "  NE name : ${EDA_NE_NAME:-eda-vne-01}"
echo "  NE type : ${EDA_NE_TYPE:-virtual-network-element}"
echo "  Listen  : ${EDA_API_HOST:-0.0.0.0}:${EDA_API_PORT:-8080}"
echo "  DB path : ${EDA_DB_PATH:-/var/lib/eda/eda.db}"

exec eda-server
