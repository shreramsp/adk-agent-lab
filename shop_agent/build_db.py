"""Builds the store's seed data as SQL files that the database runs on its first start.

    python shop_agent/build_db.py catalog      # writes db/02_catalog.sql (free)
    python shop_agent/build_db.py embeddings   # writes db/03_embeddings.sql (calls Gemini, < $0.001)

Embeddings are made once here and committed, so setting up the store needs no API calls. Toolbox
only embeds the shopper's question at search time. Both use the same model, size, and task type,
so the two sets of numbers can be compared.
"""

import os
import sys
from pathlib import Path

HERE = Path(__file__).parent
EMBED_MODEL = "gemini-embedding-001"
EMBED_DIM = 768
EMBED_TASK = "SEMANTIC_SIMILARITY"  # the task type MCP Toolbox uses for questions

SHOE = ["7", "8", "9", "9.5", "10", "11", "12"]
APPAREL = ["XS", "S", "M", "L", "XL"]
SML = ["S", "M", "L"]
ONE = ["One Size"]

# (name, brand, category, sport, price, sizes, description). Made-up brands and products.
PRODUCTS = [
    ("Cloudrunner 3", "Swiftfoot", "Running Shoes", "Running", 129.99, SHOE,
     "Lightweight neutral road running shoe with a soft foam midsole for daily training and long easy miles. Breathable mesh upper; not waterproof."),
    ("Tempo Racer", "Swiftfoot", "Running Shoes", "Running", 159.99, SHOE,
     "Carbon-plated racing shoe for 5K to marathon race day. Very light and bouncy with a firm, fast ride and minimal cushioning."),
    ("StormGuard Runner", "Nimbus Athletics", "Running Shoes", "Running", 139.99, SHOE,
     "Waterproof road running shoe with a sealed membrane and grippy rubber outsole for running in the rain on wet streets. Keeps feet dry through puddles."),
    ("Stability Plus", "Nimbus Athletics", "Running Shoes", "Running", 119.99, SHOE,
     "Supportive stability running shoe for overpronation and flat feet, with a firm medial post and a wide toe box."),
    ("Comfort Walk", "Nimbus Athletics", "Walking Shoes", "Walking", 89.99, SHOE,
     "Cushioned walking shoe for all-day comfort, standing at work, and travel. Slip-resistant sole."),
    ("Ridge GTX", "Trailborn", "Trail Shoes", "Trail Running", 149.99, SHOE,
     "Waterproof trail running shoe with deep lugs for mud, rain, and wet rocky trails. A rock plate protects from sharp stones."),
    ("Desert Glide", "Trailborn", "Trail Shoes", "Trail Running", 124.99, SHOE,
     "Breathable, quick-drying trail shoe for hot, dry desert and dusty summer trails. Sand-blocking mesh upper."),
    ("Summit Hiker Mid", "Trailborn", "Hiking Boots", "Hiking", 179.99, SHOE,
     "Mid-cut waterproof hiking boot with ankle support for multi-day backpacking with heavy loads. Sticky rubber sole."),
    ("Downpour Shell", "Peakline", "Rain Jackets", "Hiking", 189.99, APPAREL,
     "Fully waterproof, breathable three-layer rain jacket with taped seams and an adjustable hood. Packs into its own pocket; built for hiking in storms."),
    ("Featherlight Wind Jacket", "Peakline", "Running Jackets", "Running", 79.99, APPAREL,
     "Ultralight windbreaker for running on cold, windy days. Water-resistant but not for heavy rain. Reflective details for night runs."),
    ("Insulated Puffer", "Peakline", "Winter Jackets", "Hiking", 219.99, APPAREL,
     "Warm down puffer jacket for freezing temperatures, winter camping, and ski trips. Lightweight and compressible."),
    ("Hi-Vis Running Vest", "Tidewater", "Running Accessories", "Running", 34.99, SML,
     "Bright reflective safety vest with a clip-on LED light for running or cycling at night and early in the morning near traffic."),
    ("Pro Tour 300", "Courtline", "Tennis Rackets", "Tennis", 219.99, ONE,
     "Control-oriented tennis racket for advanced players: 300 g, 98 sq in head, for flat, powerful strokes."),
    ("Ace Lite", "Courtline", "Tennis Rackets", "Tennis", 99.99, ONE,
     "Lightweight, forgiving tennis racket with a large sweet spot for beginners and juniors learning the game."),
    ("Clay Court Shoe", "Courtline", "Tennis Shoes", "Tennis", 109.99, SHOE,
     "Tennis shoe with a herringbone outsole for clay courts and quick side-to-side movement. Durable toe guard."),
    ("Championship Balls 4-Pack", "Courtline", "Tennis Balls", "Tennis", 7.99, ONE,
     "Pressurized extra-duty tennis balls for hard courts."),
    ("Aero Road Helmet", "VeloForge", "Cycling Helmets", "Cycling", 149.99, SML,
     "Aerodynamic road cycling helmet with rotational impact protection and strong ventilation for fast rides."),
    ("Commuter Helmet with Light", "VeloForge", "Cycling Helmets", "Cycling", 69.99, SML,
     "Urban bike helmet with a built-in rear LED light for commuting in city traffic at night."),
    ("Padded Bib Shorts", "VeloForge", "Cycling Apparel", "Cycling", 89.99, APPAREL,
     "Cycling bib shorts with a dense chamois pad for long hours in the saddle."),
    ("Rain Cape", "VeloForge", "Cycling Apparel", "Cycling", 59.99, SML,
     "Waterproof cycling rain cape that covers your hands and handlebars when commuting by bike in the rain."),
    ("Mini Pump", "VeloForge", "Cycling Accessories", "Cycling", 24.99, ONE,
     "Compact hand pump for road and mountain bike tires that fits in a jersey pocket."),
    ("Grip Pro Yoga Mat", "Zenmat", "Yoga Mats", "Yoga", 89.99, ONE,
     "Non-slip natural rubber yoga mat for hot yoga and sweaty practice. 5 mm thick, with extra grip when wet."),
    ("Travel Fold Mat", "Zenmat", "Yoga Mats", "Yoga", 39.99, ONE,
     "Thin 1.5 mm foldable yoga mat that fits in a suitcase, for practicing yoga while traveling."),
    ("Cork Yoga Block 2-Pack", "Zenmat", "Yoga Accessories", "Yoga", 24.99, ONE,
     "Eco-friendly cork blocks that give support in poses and help with flexibility work."),
    ("Seamless Leggings", "Zenmat", "Yoga Apparel", "Yoga", 64.99, APPAREL,
     "High-waisted, squat-proof leggings with four-way stretch for yoga, pilates, and the gym."),
    ("Adjustable Dumbbells", "Ridgeback Gear", "Strength Training", "Fitness", 299.99, ONE,
     "Pair of adjustable dumbbells from 2 to 24 kg with a quick-change dial, saving space in a home gym."),
    ("Resistance Bands Set", "Ridgeback Gear", "Strength Training", "Fitness", 29.99, ONE,
     "Five latex resistance bands with handles for home workouts, physical therapy, and travel."),
    ("Speed Jump Rope", "Ridgeback Gear", "Cardio", "Fitness", 19.99, ONE,
     "Ball-bearing speed rope for cardio, boxing training, and double-unders."),
    ("Foam Roller", "Ridgeback Gear", "Recovery", "Fitness", 34.99, ONE,
     "High-density foam roller for muscle recovery and self-massage after running or lifting."),
    ("Anti-Fog Goggles", "AquaStride", "Swimming Goggles", "Swimming", 24.99, ONE,
     "Anti-fog, UV-protected swim goggles with a wide field of view for pool laps and open water."),
    ("Performance Swimsuit", "AquaStride", "Swimwear", "Swimming", 74.99, APPAREL,
     "Chlorine-resistant competitive swimsuit for training and racing in the pool."),
    ("Open Water Wetsuit", "AquaStride", "Wetsuits", "Triathlon", 349.99, APPAREL,
     "Neoprene triathlon wetsuit for open-water swimming in cold lakes and the sea; buoyant, with flexible shoulders."),
    ("Court Elite", "Nimbus Athletics", "Basketball Shoes", "Basketball", 139.99, SHOE,
     "High-top basketball shoe with ankle support and responsive cushioning for jumping and quick cuts on indoor courts."),
    ("Indoor Basketball", "Ridgeback Gear", "Basketballs", "Basketball", 49.99, ONE,
     "Official size 7 composite leather basketball with great grip for indoor games."),
    ("Firm Ground Cleats", "Swiftfoot", "Soccer Cleats", "Soccer", 119.99, SHOE,
     "Soccer cleats with molded studs for firm natural-grass pitches and a light upper for a clean touch on the ball."),
    ("Match Soccer Ball", "Ridgeback Gear", "Soccer Balls", "Soccer", 39.99, ONE,
     "Size 5 thermally bonded soccer ball for training and matches."),
    ("Trail Daypack 22L", "Peakline", "Backpacks", "Hiking", 99.99, ONE,
     "22-liter hiking daypack with a rain cover, hydration sleeve, and ventilated back panel."),
    ("Insulated Bottle 1L", "Tidewater", "Hydration", "Hiking", 32.99, ONE,
     "Double-wall steel bottle that keeps drinks cold for 24 hours on hikes and at the gym."),
    ("Running Hydration Vest", "Tidewater", "Running Accessories", "Running", 119.99, SML,
     "Lightweight running vest with two soft flasks for long trail runs and ultramarathons."),
    ("Merino Hiking Socks 3-Pack", "Peakline", "Socks", "Hiking", 44.99, SML,
     "Merino wool socks that stay warm when wet, resist odor, and prevent blisters on long hikes."),
    ("Running Socks 3-Pack", "Swiftfoot", "Socks", "Running", 19.99, SML,
     "Thin, moisture-wicking running socks with arch support and a no-show cut."),
    ("GPS Running Watch", "Nimbus Athletics", "Electronics", "Running", 249.99, ONE,
     "GPS running watch with heart rate, pace, and training plans, and a 14-day battery."),
]

# Fixed stock problems, so demos and tests are predictable: (product_id, size) -> stock
STOCK_OVERRIDES = {(6, "10"): 0, (3, "12"): 0, (9, "M"): 1}


def _q(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def stock_for(pid: int, i: int) -> int:
    return STOCK_OVERRIDES.get((pid, PRODUCTS[pid - 1][5][i]), (pid * 7 + i * 5) % 9 + 1)


def embed_text(p: tuple) -> str:
    name, brand, category, sport, _price, _sizes, desc = p
    return f"{brand} {name}. {category} for {sport}. {desc}"


def write_catalog() -> None:
    lines = ["-- Generated by build_db.py: products, stock per size, and one past order for another user.",
             "INSERT INTO products (product_id, name, brand, category, sport, price, description) VALUES"]
    rows = [f"({pid}, {_q(n)}, {_q(b)}, {_q(c)}, {_q(s)}, {pr}, {_q(d)})"
            for pid, (n, b, c, s, pr, _sz, d) in enumerate(PRODUCTS, 1)]
    lines.append(",\n".join(rows) + ";")
    lines.append("SELECT setval('products_product_id_seq', (SELECT max(product_id) FROM products));\n")
    inv = [f"({pid}, {_q(size)}, {stock_for(pid, i)})"
           for pid, p in enumerate(PRODUCTS, 1) for i, size in enumerate(p[5])]
    lines.append("INSERT INTO inventory (product_id, size, stock) VALUES\n" + ",\n".join(inv) + ";\n")
    lines.append("-- 'alice' has a past order. Other users must never see it (identity is enforced by the agent).")
    lines.append("INSERT INTO orders (order_id, user_id, status, total, created_at) VALUES "
                 "(1, 'alice', 'Delivered', 154.98, now() - interval '9 days');")
    lines.append("INSERT INTO order_items (order_id, product_id, size, quantity, unit_price) VALUES "
                 "(1, 1, '9', 1, 129.99), (1, 21, 'One Size', 1, 24.99);")
    lines.append("SELECT setval('orders_order_id_seq', 1);")
    (HERE / "db" / "02_catalog.sql").write_text("\n".join(lines) + "\n")
    print(f"wrote db/02_catalog.sql: {len(PRODUCTS)} products, {len(inv)} stock rows")


def write_embeddings() -> None:
    from dotenv import load_dotenv
    from google import genai
    from google.genai import types

    load_dotenv(HERE / ".env")
    client = genai.Client()  # AI Studio key from GOOGLE_API_KEY
    texts = [embed_text(p) for p in PRODUCTS]
    result = client.models.embed_content(
        model=EMBED_MODEL, contents=texts,
        config=types.EmbedContentConfig(task_type=EMBED_TASK, output_dimensionality=EMBED_DIM))
    lines = [f"-- Generated by build_db.py with {EMBED_MODEL} ({EMBED_DIM} dims, {EMBED_TASK}).",
             "-- Embeds 'brand name. category for sport. description' for each product."]
    for pid, emb in enumerate(result.embeddings, 1):
        vec = "[" + ",".join(f"{v:.6f}" for v in emb.values) + "]"
        lines.append(f"UPDATE products SET embedding = '{vec}' WHERE product_id = {pid};")
    lines += [
        "",
        "-- ScaNN: AlloyDB's approximate nearest-neighbour index, using cosine distance (the <=> operator).",
        "-- num_leaves ~ sqrt(rows); with a small catalog this is mostly a demonstration, the planner may",
        "-- still choose a plain scan.",
        "CREATE INDEX products_embedding_scann ON products USING scann (embedding cosine) WITH (num_leaves = 6);",
        "ANALYZE products;",
    ]
    (HERE / "db" / "03_embeddings.sql").write_text("\n".join(lines) + "\n")
    tokens = sum(len(t.split()) for t in texts) * 1.3
    print(f"wrote db/03_embeddings.sql: {len(result.embeddings)} vectors (~{tokens:.0f} tokens embedded)")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "catalog":
        write_catalog()
    elif cmd == "embeddings":
        write_embeddings()
    else:
        sys.exit(__doc__)
