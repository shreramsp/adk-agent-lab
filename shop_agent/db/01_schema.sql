-- Schema for Summit Sports (a made-up store). Runs once, when the container first starts.

CREATE EXTENSION IF NOT EXISTS vector;         -- pgvector: the `vector` type and the <=> distance operator
CREATE EXTENSION IF NOT EXISTS alloydb_scann;  -- AlloyDB's ScaNN vector index (Google's nearest-neighbour search)

CREATE TABLE products (
    product_id   SERIAL PRIMARY KEY,
    name         TEXT NOT NULL,
    brand        TEXT NOT NULL,
    category     TEXT NOT NULL,           -- e.g. 'Running Shoes', 'Rain Jackets'
    sport        TEXT NOT NULL,
    description  TEXT NOT NULL,           -- this text is what gets embedded
    price        NUMERIC(8, 2) NOT NULL CHECK (price > 0),
    embedding    vector(768)              -- meaning of name + description, from gemini-embedding-001
);

-- Stock per size. CHECK (stock >= 0) is the last line of defence: if any statement would sell more
-- than we have, the database rejects it and the whole statement (the whole order) rolls back.
CREATE TABLE inventory (
    product_id  INTEGER NOT NULL REFERENCES products(product_id),
    size        TEXT NOT NULL,            -- US shoe size ('9.5'), apparel ('M'), or 'One Size'
    stock       INTEGER NOT NULL CHECK (stock >= 0),
    PRIMARY KEY (product_id, size)
);

-- user_id is the ADK session's user, set by the agent's code, never chosen by the model.
CREATE TABLE shopping_list (
    user_id     TEXT NOT NULL,
    product_id  INTEGER NOT NULL,
    size        TEXT NOT NULL,
    quantity    INTEGER NOT NULL CHECK (quantity BETWEEN 1 AND 10),
    added_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, product_id, size),
    FOREIGN KEY (product_id, size) REFERENCES inventory(product_id, size)  -- the size must exist
);

CREATE TABLE orders (
    order_id    SERIAL PRIMARY KEY,
    user_id     TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'Placed'
                CHECK (status IN ('Placed', 'Shipped', 'Delivered', 'Cancelled')),
    total       NUMERIC(10, 2) NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE order_items (
    order_id    INTEGER NOT NULL REFERENCES orders(order_id),
    product_id  INTEGER NOT NULL,
    size        TEXT NOT NULL,
    quantity    INTEGER NOT NULL CHECK (quantity > 0),
    unit_price  NUMERIC(8, 2) NOT NULL,   -- price at the time of the order
    PRIMARY KEY (order_id, product_id, size),
    FOREIGN KEY (product_id, size) REFERENCES inventory(product_id, size)
);

CREATE INDEX orders_user ON orders (user_id, created_at DESC);
