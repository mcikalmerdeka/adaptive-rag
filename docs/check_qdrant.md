Same pattern — a few options:

**1. Qdrant Dashboard (easiest)**

Open `http://localhost:6333/dashboard` in your browser. You'll see all collections, can browse points, run test queries, etc.

**2. REST API**

List collections:

```bash
curl http://localhost:6333/collections
```

Collection info (point count, vector config):

```bash
curl http://localhost:6333/collections/adaptive_rag
```

**3. Python one-liner**

```bash
uv run --no-sync python -c "
from src.indexing import QdrantStore
store = QdrantStore()
docs = store.list_documents()
print(f'{len(docs)} documents indexed')
for d in docs:
    print(f'  {d[\"filename\"]}  chunks={d[\"chunks\"]}  doc_id={d[\"doc_id\"][:16]}')
"
```

This uses the same `list_documents()` you already see in the Ingest tab — it reads from the `doc_id` payload index.

**4. Direct qdrant-client**

```bash
uv run --no-sync python -c "
from qdrant_client import QdrantClient
c = QdrantClient(url='http://localhost:6333')
info = c.get_collection('adaptive_rag')
print('vectors:', info.vectors_count)
print('points:', info.points_count)
print('status:', info.status)
"
```

The dashboard (`/dashboard`) is the most useful day-to-day since you can visually browse points and run ad-hoc searches without writing code.
