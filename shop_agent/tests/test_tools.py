"""Tests for the shop's database tools, called over MCP exactly like the agent calls them (free: no
model or embedding calls). Needs the database and Toolbox running:

    docker compose -f shop_agent/docker-compose.yml up -d --wait
    ./shop_agent/run_toolbox.sh            # in another terminal
    python -m unittest discover -s shop_agent/tests -t . -v

Each run uses a fresh test user, and every order it places is cancelled again, so stock is unchanged
(the cancelled test orders stay in the table; `docker compose ... down -v` resets everything).
"""

import asyncio
import json
import unittest
import urllib.request
import uuid
from types import SimpleNamespace

from shop_agent import agent, config


def _toolbox_up() -> bool:
    try:
        urllib.request.urlopen(config.TOOLBOX_URL.rsplit("/mcp", 1)[0] + "/", timeout=2)
        return True
    except OSError:
        return False


def rows(result) -> list[dict]:
    """MCP tool result -> list of row dicts (Toolbox returns one JSON row per text part)."""
    if result.get("isError") or "error" in result:
        raise RuntimeError(json.dumps(result)[:400])
    return [json.loads(c["text"]) for c in result.get("content", []) if c.get("text", "").startswith("{")]


@unittest.skipUnless(_toolbox_up(), "Toolbox for the shop is not running on " + config.TOOLBOX_URL)
class ShopToolsTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.user = f"test-{uuid.uuid4().hex[:8]}"
        self.tools = {}
        for ts in agent.root_agent.tools:
            for t in await ts.get_tools():
                self.tools[t.name] = t

    async def asyncTearDown(self):
        for ts in agent.root_agent.tools:
            await ts.close()

    async def call(self, name: str, **args):
        if name in config.USER_TOOLS:
            args["user_id"] = self.user
        # call the MCP tool's parent run_async: skips ADK's approval pause, which only works in a real session
        return await super(type(self.tools[name]), self.tools[name]).run_async(args=args, tool_context=None)

    async def stock(self, product_id: int, size: str) -> int:
        (d,) = rows(await self.call("product-details", product_id=product_id))
        return d["stock_by_size"][size]

    async def test_order_lowers_stock_and_cancel_restores_it(self):
        before = await self.stock(1, "10")
        qty = min(2, before)
        self.assertGreater(qty, 0, "test needs Cloudrunner 3 size 10 in stock")
        rows(await self.call("add-to-shopping-list", product_id=1, size="10", quantity=qty))
        (line,) = rows(await self.call("show-shopping-list"))
        self.assertEqual((line["quantity"], float(line["list_total"])), (qty, round(129.99 * qty, 2)))

        (placed,) = rows(await self.call("place-order"))
        self.assertEqual(placed["result"], "placed")
        self.assertEqual(await self.stock(1, "10"), before - qty)
        self.assertEqual(rows(await self.call("show-shopping-list")), [])  # list emptied

        (order,) = rows(await self.call("my-orders"))
        self.assertEqual((order["order_id"], order["status"]), (placed["order_id"], "Placed"))

        (cancel,) = rows(await self.call("cancel-order", order_id=placed["order_id"]))
        self.assertEqual(cancel["result"], "cancelled")
        self.assertEqual(await self.stock(1, "10"), before)
        (again,) = rows(await self.call("cancel-order", order_id=placed["order_id"]))  # only once
        self.assertTrue(again["result"].startswith("not cancelled"))

    async def test_all_or_nothing_when_one_item_is_out_of_stock(self):
        before = await self.stock(1, "9")
        rows(await self.call("add-to-shopping-list", product_id=1, size="9"))
        rows(await self.call("add-to-shopping-list", product_id=6, size="10"))  # Ridge GTX size 10: stock 0
        (r,) = rows(await self.call("place-order"))
        self.assertIn("not enough stock for Trailborn Ridge GTX size 10", r["result"])
        self.assertIsNone(r["order_id"])
        self.assertEqual(await self.stock(1, "9"), before)  # the in-stock item was not sold either
        self.assertEqual(len(rows(await self.call("show-shopping-list"))), 2)  # list kept
        self.assertEqual(rows(await self.call("my-orders")), [])
        for pid, size in ((1, "9"), (6, "10")):
            rows(await self.call("remove-from-shopping-list", product_id=pid, size=size))

    async def test_empty_list_cannot_be_ordered(self):
        (r,) = rows(await self.call("place-order"))
        self.assertEqual(r["result"], "not placed: the shopping list is empty")

    async def test_unknown_size_and_too_many_are_rejected(self):
        with self.assertRaises(Exception):  # foreign key: product 1 has no size 15
            rows(await self.call("add-to-shopping-list", product_id=1, size="15"))
        with self.assertRaises(Exception):  # Toolbox maxValue: 1 to 5
            rows(await self.call("add-to-shopping-list", product_id=1, size="9", quantity=50))

    async def test_cannot_cancel_someone_elses_order(self):
        (r,) = rows(await self.call("cancel-order", order_id=1))  # order 1 belongs to alice
        self.assertTrue(r["result"].startswith("not cancelled"))

    async def test_similar_products_needs_no_embedding_call(self):
        sims = rows(await self.call("similar-products", product_id=3))
        if sims and sims[0]["similarity"] is None:
            self.skipTest("embeddings not loaded yet")
        self.assertEqual(len(sims), 4)


class IdentityTest(unittest.TestCase):
    def test_model_cannot_choose_the_user(self):
        args = {"user_id": "alice"}
        agent.enforce_identity(SimpleNamespace(name="my-orders"), args, SimpleNamespace(user_id="bob"))
        self.assertEqual(args["user_id"], "bob")

    def test_other_tools_are_untouched(self):
        args = {"query": "rain shoes"}
        agent.enforce_identity(SimpleNamespace(name="search-products"), args, SimpleNamespace(user_id="bob"))
        self.assertEqual(args, {"query": "rain shoes"})


if __name__ == "__main__":
    unittest.main()
