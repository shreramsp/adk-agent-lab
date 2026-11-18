#!/usr/bin/env bash
# Starts MCP Toolbox for the shop agent on http://127.0.0.1:5001/mcp (localhost only).
# Loads .env so tools.yaml gets the DB settings and Toolbox gets GOOGLE_API_KEY for embeddings.
# Leave it running in its own terminal while you use adk web.
set -euo pipefail
cd "$(dirname "$0")"

# Use this folder's toolbox binary, or reuse the one downloaded for the bug assistant.
TOOLBOX=./toolbox
[[ -x "$TOOLBOX" ]] || TOOLBOX=../bug_assistant_agent/toolbox
if [[ ! -x "$TOOLBOX" ]]; then
  echo "toolbox binary not found. Download it first (see README)." >&2
  exit 1
fi

set -a; source .env; set +a
# localhost only, and only local hosts/origins: no other website in your browser can call these tools
exec "$TOOLBOX" --config tools.yaml --address 127.0.0.1 --port 5001 \
  --allowed-hosts 127.0.0.1,localhost \
  --allowed-origins http://127.0.0.1:5001,http://localhost:5001
