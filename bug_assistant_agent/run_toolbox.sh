#!/usr/bin/env bash
# Starts the MCP Toolbox server for the bug assistant.
# Loads the DB settings from .env (so tools.yaml can use ${DB_HOST} etc.), then serves the tools
# over MCP at http://127.0.0.1:5000/mcp. Leave this running in its own terminal while you use adk web.
set -euo pipefail
cd "$(dirname "$0")"                     # work from this folder no matter where it's called from

if [[ ! -x ./toolbox ]]; then            # the binary isn't in git; tell the user how to get it
  echo "toolbox binary not found. Download it first (see README)." >&2
  exit 1
fi

set -a; source .env; set +a              # export every line in .env as an environment variable
# --address: listen on this Mac only, not your whole network.
# --allowed-hosts / --allowed-origins: the default "*" lets any website open in your browser call
# these tools (and write tickets). Locking them to localhost blocks that; the Python MCP client is unaffected.
exec ./toolbox --config tools.yaml --address 127.0.0.1 --port 5000 \
  --allowed-hosts 127.0.0.1,localhost \
  --allowed-origins http://127.0.0.1:5000,http://localhost:5000
