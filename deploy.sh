#!/usr/bin/env bash
set -euo pipefail

# Load env
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"

if [[ ! -f "$ENV_FILE" ]]; then
    echo "Error: .env file not found. Copy .env.example to .env and fill it in."
    exit 1
fi

source "$ENV_FILE"

: "${DEPLOY_HOST:?DEPLOY_HOST not set in .env}"
: "${DEPLOY_USER:?DEPLOY_USER not set in .env}"
: "${DEPLOY_PATH:?DEPLOY_PATH not set in .env}"

REMOTE="${DEPLOY_USER}@${DEPLOY_HOST}"

echo "==> Syncing files to ${REMOTE}:${DEPLOY_PATH}..."
rsync -avz --exclude='.DS_Store' \
           --exclude='.git/' \
           --exclude='uploads/' \
           --exclude='__pycache__/' \
           --exclude='*.pyc' \
           "$SCRIPT_DIR/" "${REMOTE}:${DEPLOY_PATH}/"

echo "==> Building and restarting container on ${REMOTE}..."
ssh "${REMOTE}" "cd ${DEPLOY_PATH} && docker compose up -d --build"

echo "==> Checking container status..."
ssh "${REMOTE}" "docker ps --filter name=transcriber --format 'Status: {{.Status}}'"

echo ""
echo "Done! App running at http://${DEPLOY_HOST}:${DEPLOY_PORT:-1337}"
