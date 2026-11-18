"""Every setting for the shop assistant in one place."""

import os

MODEL = "gemini-3.5-flash-lite"

# MCP Toolbox for this agent (run_toolbox.sh). adk web loads .env first, so TOOLBOX_URL can override it.
TOOLBOX_URL = os.getenv("TOOLBOX_URL", "http://127.0.0.1:5001/mcp")

# Toolbox tools split by risk (same server, three toolsets):
BROWSE_TOOLS = ["search-products", "product-details", "similar-products", "show-shopping-list", "my-orders"]
CART_TOOLS = ["add-to-shopping-list", "remove-from-shopping-list"]  # easy to undo: no approval
ORDER_TOOLS = ["place-order", "cancel-order"]  # money and stock: a person must approve each call

# Tools whose user_id is always set from the ADK session, never taken from the model.
USER_TOOLS = ["show-shopping-list", "my-orders", "add-to-shopping-list", "remove-from-shopping-list",
              "place-order", "cancel-order"]

# Below this match_score the agent calls the results weak and asks a clarifying question.
# Measured, not guessed: gemini-embedding-001 scores sit in a narrow band. Real matches scored 0.88-0.93,
# while unrelated requests ("chess set", "laptop charger") still scored ~0.77 against the best product.
WEAK_MATCH = 0.80
