A few ways, pick your preferred:

**1. Via Docker (no extra tools needed)**

```bash
docker exec -it adaptive_rag_postgres psql -U adaptive_rag -d adaptive_rag -c "\dt"
```

Lists all tables in the `adaptive_rag` database.

To see all databases:

```bash
docker exec -it adaptive_rag_postgres psql -U adaptive_rag -c "\l"
```

**2. Via `psql` from host (if you have it installed)**

```bash
psql postgresql://adaptive_rag:adaptive_rag@localhost:5433/adaptive_rag -c "\dt"
```

**3. Via our seed script's output (already ran)**

You already saw this at the end of the seed run:

```
Row counts: customers=100, products=50, orders=500, order_items=1287, refunds=35
```

**4. Quick one-liner with Python/SQLAlchemy (same creds as the app)**

```bash
uv run --no-sync python -c "
from src.tools import SqlTool
t = SqlTool()
print(t.schema_text)
"
```

This gives you the full DDL-style introspection that the SQL tool already uses internally — columns, types, PKs, FKs.

The databases in the container are just the one (`adaptive_rag`) plus the default Postgres system databases (`postgres`, `template0`, `template1`). The app only touches `adaptive_rag`.

---

---

Simplest way is through the Docker `psql`:

**Check columns of a table:**

```bash
docker exec -it adaptive_rag_postgres psql -U adaptive_rag -d adaptive_rag -c "\d orders"
```

**First 5 rows of any table:**

```bash
docker exec -it adaptive_rag_postgres psql -U adaptive_rag -d adaptive_rag -c "SELECT * FROM orders LIMIT 5;"
```

**All at once — columns + sample rows for every table:**

```bash
docker exec -it adaptive_rag_postgres psql -U adaptive_rag -d adaptive_rag -c "
\d customers
\d products
\d orders
\d order_items
\d refunds
SELECT * FROM customers LIMIT 3;
SELECT * FROM orders LIMIT 3;
"
```

Or via Python if you prefer staying in the project:

```bash
uv run --no-sync python -c "
from src.tools import SqlTool
t = SqlTool()
print(t.schema_text)
"
```

That prints the full introspected schema (column names, types, PKs, FKs) for all tables — same thing the SQL LLM sees when generating queries.

For ad-hoc row previews without leaving the terminal:

```bash
uv run --no-sync python -c "
from src.tools import SqlTool
t = SqlTool()
for tbl in ['customers', 'products', 'orders', 'order_items', 'refunds']:
    r = t.execute(f'SELECT * FROM {tbl} LIMIT 3')
    print(f'=== {tbl} ===')
    if r.rows:
        print('  ' + ' | '.join(r.columns))
        for row in r.rows:
            print('  ' + ' | '.join(str(v) for v in row.values()))
    print()
"
```
