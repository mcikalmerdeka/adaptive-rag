"""Seed the demo Postgres with a small e-commerce dataset.

Usage:
    uv run python scripts/seed_demo_data.py             # idempotent re-seed
    uv run python scripts/seed_demo_data.py --recreate  # drop everything first

Connects to ``SQL_DATABASE_URL`` if set, else assumes the bundled
docker-compose Postgres at ``postgresql+psycopg://adaptive_rag:adaptive_rag@localhost:5432/adaptive_rag``.

Creates:

- 5 base tables (customers, products, orders, order_items, refunds)
- ~100 customers, ~50 products, ~500 orders, ~1000 line items, ~50 refunds
- A dedicated ``adaptive_rag_ro`` read-only role with SELECT grants only

The data is generated with a fixed RNG seed so re-running gives the same
rows back. Useful for repeatable demos and eval.
"""

from __future__ import annotations

import argparse
import logging
import random
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.engine import Engine  # noqa: E402

from src.config import settings  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("seed_demo_data")


# ---- defaults --------------------------------------------------------------

DEFAULT_ADMIN_URL = "postgresql+psycopg://adaptive_rag:adaptive_rag@localhost:5433/adaptive_rag"
RO_ROLE = "adaptive_rag_ro"
RO_PASSWORD = "adaptive_rag_ro"

RNG_SEED = 42

# Keep the dataset deliberately small — large enough for non-trivial queries,
# small enough to seed in <1s and reason about by hand.
N_CUSTOMERS = 100
N_PRODUCTS = 50
N_ORDERS = 500
REFUND_RATE = 0.10  # ~10% of completed orders get refunded


# ---- DDL -------------------------------------------------------------------

DROP_SQL = """
DROP TABLE IF EXISTS refunds CASCADE;
DROP TABLE IF EXISTS order_items CASCADE;
DROP TABLE IF EXISTS orders CASCADE;
DROP TABLE IF EXISTS products CASCADE;
DROP TABLE IF EXISTS customers CASCADE;
"""

CREATE_SQL = """
CREATE TABLE IF NOT EXISTS customers (
    id              SERIAL PRIMARY KEY,
    name            TEXT NOT NULL,
    email           TEXT NOT NULL UNIQUE,
    country         TEXT NOT NULL,
    signup_date     DATE NOT NULL
);

CREATE TABLE IF NOT EXISTS products (
    id              SERIAL PRIMARY KEY,
    name            TEXT NOT NULL,
    category        TEXT NOT NULL,
    price           NUMERIC(10, 2) NOT NULL,
    stock           INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS orders (
    id              SERIAL PRIMARY KEY,
    customer_id     INTEGER NOT NULL REFERENCES customers(id),
    status          TEXT NOT NULL CHECK (status IN ('pending', 'completed', 'refunded', 'cancelled')),
    total           NUMERIC(10, 2) NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS order_items (
    id              SERIAL PRIMARY KEY,
    order_id        INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    product_id      INTEGER NOT NULL REFERENCES products(id),
    quantity        INTEGER NOT NULL CHECK (quantity > 0),
    unit_price      NUMERIC(10, 2) NOT NULL
);

CREATE TABLE IF NOT EXISTS refunds (
    id              SERIAL PRIMARY KEY,
    order_id        INTEGER NOT NULL UNIQUE REFERENCES orders(id),
    amount          NUMERIC(10, 2) NOT NULL,
    reason          TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_orders_created_at ON orders(created_at);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
CREATE INDEX IF NOT EXISTS idx_orders_customer_id ON orders(customer_id);
CREATE INDEX IF NOT EXISTS idx_order_items_order_id ON order_items(order_id);
CREATE INDEX IF NOT EXISTS idx_refunds_created_at ON refunds(created_at);
"""


# ---- synthetic data --------------------------------------------------------

FIRST_NAMES = [
    "Alex", "Sam", "Jordan", "Taylor", "Morgan", "Riley", "Casey", "Avery",
    "Quinn", "Skyler", "Kai", "Aditi", "Wei", "Yuki", "Hugo", "Leila",
    "Mateo", "Priya", "Sven", "Mia", "Ravi", "Jin", "Noor", "Ezra",
]
LAST_NAMES = [
    "Lopez", "Smith", "Patel", "Nguyen", "Tanaka", "Müller", "Rossi",
    "Kim", "Cohen", "García", "Sato", "Singh", "Lee", "Wang", "Khan",
    "Andersen", "Dubois", "Silva", "Costa", "Brown", "Jones", "Davies",
]
COUNTRIES = ["US", "UK", "DE", "JP", "BR", "ID", "IN", "FR", "AU", "CA"]

PRODUCT_TEMPLATES = [
    ("Wireless Headphones",   "audio",       129.99),
    ("USB-C Charger",         "accessories",  29.99),
    ("4K Webcam",             "video",       149.99),
    ("Mechanical Keyboard",   "input",       189.00),
    ("Ergonomic Mouse",       "input",        69.50),
    ("Standing Desk Mat",     "furniture",    79.00),
    ("Noise-Cancelling Buds", "audio",       199.00),
    ("HDMI Cable 2m",         "accessories",  14.99),
    ("Laptop Stand",          "furniture",    49.00),
    ("Webcam Privacy Cover",  "accessories",   9.99),
]

REFUND_REASONS = [
    "defective on arrival",
    "wrong item shipped",
    "no longer needed",
    "did not match description",
    "shipping took too long",
    "found cheaper elsewhere",
]


def _seed_customers(conn, rng: random.Random) -> int:
    rows = []
    today = date.today()
    used_emails: set[str] = set()
    for i in range(1, N_CUSTOMERS + 1):
        first = rng.choice(FIRST_NAMES)
        last = rng.choice(LAST_NAMES)
        country = rng.choice(COUNTRIES)
        signup = today - timedelta(days=rng.randint(1, 730))
        # Disambiguate duplicate emails deterministically.
        suffix = i
        while True:
            email = f"{first.lower()}.{last.lower()}{suffix}@example.com"
            if email not in used_emails:
                break
            suffix += 1
        used_emails.add(email)
        rows.append(
            {
                "name": f"{first} {last}",
                "email": email,
                "country": country,
                "signup_date": signup,
            }
        )
    conn.execute(
        text(
            "INSERT INTO customers (name, email, country, signup_date) "
            "VALUES (:name, :email, :country, :signup_date)"
        ),
        rows,
    )
    return len(rows)


def _seed_products(conn, rng: random.Random) -> int:
    rows = []
    for i in range(N_PRODUCTS):
        base = PRODUCT_TEMPLATES[i % len(PRODUCT_TEMPLATES)]
        name, category, base_price = base
        # Variant suffix so we get N_PRODUCTS rows with stable names.
        variant = chr(ord("A") + (i // len(PRODUCT_TEMPLATES)))
        full_name = f"{name} {variant}" if i >= len(PRODUCT_TEMPLATES) else name
        rows.append(
            {
                "name": full_name,
                "category": category,
                "price": Decimal(str(round(base_price * rng.uniform(0.9, 1.1), 2))),
                "stock": rng.randint(0, 200),
            }
        )
    conn.execute(
        text(
            "INSERT INTO products (name, category, price, stock) "
            "VALUES (:name, :category, :price, :stock)"
        ),
        rows,
    )
    return len(rows)


def _seed_orders_and_items(conn, rng: random.Random) -> tuple[int, int, int]:
    customer_ids = [r[0] for r in conn.execute(text("SELECT id FROM customers")).all()]
    products = conn.execute(text("SELECT id, price FROM products")).all()

    now = datetime.now(timezone.utc)
    # Single-row inserts: psycopg3 + SQLAlchemy's executemany doesn't
    # reliably return rows from RETURNING. 500 individual inserts is still
    # well under a second and keeps the script simple.
    insert_order = text(
        "INSERT INTO orders (customer_id, status, total, created_at) "
        "VALUES (:customer_id, :status, :total, :created_at) "
        "RETURNING id"
    )
    order_ids: list[int] = []
    for _ in range(N_ORDERS):
        customer_id = rng.choice(customer_ids)
        status = rng.choices(
            ["completed", "pending", "cancelled"],
            weights=[0.75, 0.15, 0.10],
            k=1,
        )[0]
        days_ago = rng.randint(0, 365)
        created_at = now - timedelta(days=days_ago, hours=rng.randint(0, 23))
        oid = conn.execute(
            insert_order,
            {
                "customer_id": customer_id,
                "status": status,
                "total": Decimal("0.00"),
                "created_at": created_at,
            },
        ).scalar_one()
        order_ids.append(oid)

    # Items: 1-4 line items per order.
    item_rows: list[dict] = []
    order_totals: dict[int, Decimal] = {oid: Decimal("0.00") for oid in order_ids}
    for oid in order_ids:
        for _ in range(rng.randint(1, 4)):
            pid, price = rng.choice(products)
            qty = rng.randint(1, 3)
            line_total = price * qty
            order_totals[oid] += line_total
            item_rows.append(
                {
                    "order_id": oid,
                    "product_id": pid,
                    "quantity": qty,
                    "unit_price": price,
                }
            )
    conn.execute(
        text(
            "INSERT INTO order_items (order_id, product_id, quantity, unit_price) "
            "VALUES (:order_id, :product_id, :quantity, :unit_price)"
        ),
        item_rows,
    )

    # Backfill order totals.
    conn.execute(
        text("UPDATE orders SET total = :total WHERE id = :id"),
        [{"id": oid, "total": tot} for oid, tot in order_totals.items()],
    )

    # Refund a fraction of completed orders.
    completed = conn.execute(
        text(
            "SELECT id, total, created_at FROM orders WHERE status = 'completed'"
        )
    ).all()
    refund_rows: list[dict] = []
    for oid, total, created_at in completed:
        if rng.random() < REFUND_RATE:
            refund_amount = total * Decimal(str(round(rng.uniform(0.3, 1.0), 2)))
            refund_rows.append(
                {
                    "order_id": oid,
                    "amount": refund_amount.quantize(Decimal("0.01")),
                    "reason": rng.choice(REFUND_REASONS),
                    "created_at": created_at + timedelta(days=rng.randint(1, 14)),
                }
            )
    if refund_rows:
        conn.execute(
            text(
                "INSERT INTO refunds (order_id, amount, reason, created_at) "
                "VALUES (:order_id, :amount, :reason, :created_at)"
            ),
            refund_rows,
        )
        # Mark those orders as refunded.
        conn.execute(
            text(
                "UPDATE orders SET status = 'refunded' "
                "WHERE id = ANY(:ids)"
            ),
            {"ids": [r["order_id"] for r in refund_rows]},
        )

    return len(order_ids), len(item_rows), len(refund_rows)


# ---- read-only role --------------------------------------------------------

# NOTE: the canonical Postgres way to safely interpolate the password into
# CREATE ROLE is ``format('... %L', pw)`` — but psycopg3 intercepts ``%``
# as a client-side placeholder. ``quote_literal`` is the equivalent that
# does not contain a ``%``.
def _ro_role_sql() -> str:
    pw_literal = "'" + RO_PASSWORD.replace("'", "''") + "'"
    return f"""
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{RO_ROLE}') THEN
        EXECUTE 'CREATE ROLE {RO_ROLE} LOGIN PASSWORD ' || quote_literal({pw_literal});
    END IF;
END $$;

GRANT CONNECT ON DATABASE adaptive_rag TO {RO_ROLE};
GRANT USAGE ON SCHEMA public TO {RO_ROLE};
GRANT SELECT ON ALL TABLES IN SCHEMA public TO {RO_ROLE};
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT ON TABLES TO {RO_ROLE};
"""


# ---- driver ----------------------------------------------------------------

def _resolve_admin_url() -> str:
    # Prefer the env var if set, else assume bundled docker compose.
    raw = settings.SQL_DATABASE_URL or DEFAULT_ADMIN_URL
    # If the env var points at the read-only role, swap to the admin role for
    # seeding (the seed needs CREATE TABLE / INSERT).
    if RO_ROLE in raw:
        logger.info(
            f"SQL_DATABASE_URL targets the read-only role; using "
            f"{DEFAULT_ADMIN_URL} for seeding instead."
        )
        return DEFAULT_ADMIN_URL
    return raw


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed demo Postgres data.")
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="Drop tables before recreating. Default appends nothing if tables exist.",
    )
    args = parser.parse_args()

    url = _resolve_admin_url()
    logger.info(f"Connecting to {_redact(url)}")

    engine: Engine = create_engine(url, isolation_level="AUTOCOMMIT", future=True)

    with engine.begin() as conn:
        if args.recreate:
            logger.info("Dropping existing tables")
            conn.exec_driver_sql(DROP_SQL)

        # Probe whether the schema is already populated.
        existing = conn.execute(
            text("SELECT to_regclass('public.customers')")
        ).scalar()
        if existing and not args.recreate:
            count = conn.execute(text("SELECT COUNT(*) FROM customers")).scalar()
            if count and count > 0:
                logger.info(
                    f"customers table already has {count} rows. "
                    "Pass --recreate to wipe and reseed."
                )
                _ensure_ro_role(conn)
                _print_summary(conn)
                return 0

        logger.info("Creating schema")
        conn.exec_driver_sql(CREATE_SQL)

        rng = random.Random(RNG_SEED)
        logger.info("Seeding customers")
        n_customers = _seed_customers(conn, rng)
        logger.info(f"  inserted {n_customers} customers")

        logger.info("Seeding products")
        n_products = _seed_products(conn, rng)
        logger.info(f"  inserted {n_products} products")

        logger.info("Seeding orders + items + refunds")
        n_orders, n_items, n_refunds = _seed_orders_and_items(conn, rng)
        logger.info(
            f"  inserted {n_orders} orders, {n_items} line items, "
            f"{n_refunds} refunds"
        )

        _ensure_ro_role(conn)
        _print_summary(conn)

    logger.info(
        f"Done. App should connect with: "
        f"{_redact(settings.SQL_DATABASE_URL or DEFAULT_ADMIN_URL)}"
    )
    return 0


def _ensure_ro_role(conn) -> None:
    logger.info(f"Ensuring read-only role '{RO_ROLE}' exists with SELECT grants")
    try:
        conn.exec_driver_sql(_ro_role_sql())
    except Exception as exc:
        logger.warning(
            f"Could not create read-only role (this is expected on managed "
            f"Postgres like Neon): {exc}"
        )


def _print_summary(conn) -> None:
    counts = conn.execute(
        text(
            """
            SELECT
                (SELECT COUNT(*) FROM customers)   AS customers,
                (SELECT COUNT(*) FROM products)    AS products,
                (SELECT COUNT(*) FROM orders)      AS orders,
                (SELECT COUNT(*) FROM order_items) AS order_items,
                (SELECT COUNT(*) FROM refunds)     AS refunds
            """
        )
    ).mappings().one()
    logger.info(
        "Row counts: " + ", ".join(f"{k}={v}" for k, v in counts.items())
    )


def _redact(url: str) -> str:
    # Hide password between user: and @host
    if "://" not in url or "@" not in url:
        return url
    scheme, rest = url.split("://", 1)
    creds, host = rest.rsplit("@", 1)
    if ":" in creds:
        user, _ = creds.split(":", 1)
        return f"{scheme}://{user}:****@{host}"
    return url


if __name__ == "__main__":
    raise SystemExit(main())
