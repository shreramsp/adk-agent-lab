"""Entry point: ADK loads `root_agent` from this file.

One LlmAgent whose tools all come from MCP Toolbox (tools.yaml) over AlloyDB Omni:
    browse toolset  - search by meaning + filters, details, "more like this", list, orders
    cart toolset    - add / remove shopping-list items
    order toolset   - place / cancel orders, each call needs a person's approval (require_confirmation)
A before_tool_callback sets user_id from the session on every call, so the model can't choose whose
shopping list or orders it sees.
"""

import logging
from typing import Any

from google.adk.agents import LlmAgent
from google.adk.models import Gemini
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.mcp_tool import McpToolset, StreamableHTTPConnectionParams
from google.adk.tools.tool_context import ToolContext
from google.genai import types

from . import config

log = logging.getLogger(__name__)


def _toolset(tool_names: list[str], **kwargs: Any) -> McpToolset:
    """One MCP connection to Toolbox that only exposes `tool_names`."""
    return McpToolset(
        connection_params=StreamableHTTPConnectionParams(url=config.TOOLBOX_URL, timeout=15),
        tool_filter=tool_names,
        **kwargs,
    )


browse_tools = _toolset(config.BROWSE_TOOLS)
cart_tools = _toolset(config.CART_TOOLS)
# ADK pauses before each call and the UI asks the shopper to approve or reject the exact arguments.
order_tools = _toolset(config.ORDER_TOOLS, require_confirmation=True)


def enforce_identity(tool: BaseTool, args: dict[str, Any], tool_context: ToolContext) -> None:
    """Runs before every tool call. For tools that read or change one shopper's data, replace whatever
    user_id the model wrote with the logged-in session user. A message like "show the orders of alice"
    then still only returns the current shopper's own orders."""
    if tool.name in config.USER_TOOLS:
        asked_for = args.get("user_id")
        args["user_id"] = tool_context.user_id
        if asked_for not in (None, "me", tool_context.user_id):
            log.warning("model asked %s for user_id=%r; used session user %r instead",
                        tool.name, asked_for, tool_context.user_id)
    return None


root_agent = LlmAgent(
    name="shop_assistant",
    model=Gemini(model=config.MODEL, retry_options=types.HttpRetryOptions(attempts=5, initial_delay=2)),
    description="Shopping assistant for Summit Sports: finds gear by meaning, manages the shopping list, and places orders.",
    instruction=(
        "You are the shopping assistant of Summit Sports, an online sports store. Be brief and friendly.\n\n"
        "Finding products:\n"
        "- For any request to find or recommend products, call search-products. Put the need (activity, "
        "conditions, features) in query. Put a budget in max_price, a size in size, and a product type word "
        "in category, but only when the shopper gave them.\n"
        "- Show each result on one line: '#ID Brand Name, $price, match 0.82, sizes: ...'. Then say in one "
        "sentence why the top results fit the request.\n"
        f"- If the best match_score is below {config.WEAK_MATCH}, say the matches are weak and ask one "
        "clarifying question.\n"
        "- Use product-details for questions about one product, and similar-products when the shopper wants "
        "alternatives or 'more like this'.\n\n"
        "Shopping list and orders:\n"
        "- user_id is filled in by the app: always pass 'me'. You can only see and change this shopper's own "
        "list and orders. If asked about another person's orders, say you can only show the shopper's own.\n"
        "- To add an item you need the product and an exact size from its sizes. If the size is missing, ask.\n"
        "- To order: first call show-shopping-list and show the items and total, then call place-order. The app "
        "asks the shopper to approve it, so do not ask 'shall I?' yourself. The same goes for cancel-order.\n"
        "- If place-order or cancel-order returns a result starting with 'not', explain why in one sentence.\n\n"
        "Only state prices, stock, sizes, and order details that came from a tool result. Never invent them."
    ),
    tools=[browse_tools, cart_tools, order_tools],
    before_tool_callback=enforce_identity,
)
