# Performance Awareness

## Mindset: Measure First, Optimize Second

Premature optimization is the root of all evil — but so is shipping code that falls over at scale. The key is knowing when to care and what to measure.

---

## The Performance Hierarchy

Optimize in this order:

1. **Algorithmic complexity** — O(n²) will always beat O(n) eventually, regardless of micro-optimizations
2. **Database queries** — N+1 queries, missing indexes, and full table scans kill performance
3. **I/O bottlenecks** — Network calls, disk reads, file system operations
4. **Memory allocation** — Excessive object creation, memory leaks, large data structures
5. **Micro-optimizations** — Loop unrolling, cache locality (last resort, measure impact)

---

## Key Metrics

### Response Time
| Target | Acceptable | Warning | Critical |
|---|---|---|---|
| API response | < 100ms | < 500ms | > 1s |
| Page load | < 1s | < 3s | > 5s |
| Database query | < 10ms | < 100ms | > 500ms |

### Throughput
- Requests per second (RPS) your system can handle
- Concurrent connections supported
- Queue depth and wait times

### Resource Utilization
- CPU: sustained > 70% is a warning
- Memory: monitor for leaks and growth over time
- Disk I/O: random reads are expensive; sequential is cheap
- Network: bandwidth and latency to dependent services

---

## Caching Strategy

### When to Cache
- **Static assets** — Cache aggressively (CDN, browser cache)
- **Database queries** — Cache results that change infrequently
- **Computed values** — Cache expensive calculations
- **API responses** — Cache external API calls with appropriate TTL

### When NOT to Cache
- **User-specific data** — unless scoped to that user
- **Real-time data** — stock prices, live feeds
- **Small, cheap computations** — cache overhead > computation cost
- **Data that must be consistent** — cache invalidation is hard

### Cache Invalidation
```
"There are only two hard things in Computer Science: 
cache invalidation and naming things."
```

- Prefer **TTL-based** expiration for simplicity
- Use **write-through** or **write-behind** for consistency-critical data
- **Never** cache without an invalidation strategy

---

## Database Performance

### Query Optimization
- **Indexing** — Index columns used in WHERE, JOIN, ORDER BY. Don't over-index (writes slow down).
- **N+1 Problem** — Fetch related data in a single query (JOIN) or batch queries
- **Pagination** — Never `SELECT *` without LIMIT on large tables
- **Explain plans** — Use `EXPLAIN` (PostgreSQL) or `EXPLAIN ANALYZE` to understand query execution

### Connection Management
- Use connection pooling (PgBouncer, SQLAlchemy pool, Prisma connection pool)
- Close connections promptly; don't leak them
- Monitor pool exhaustion

---

## Async & Concurrency

### When to Use Async
- **I/O-bound work** — API calls, database queries, file reads
- **Many concurrent operations** — handling thousands of connections
- **Not for CPU-bound work** — use threads/processes instead

### Concurrency Patterns
- **Batching** — Group small operations into larger ones
- **Parallelization** — Run independent operations concurrently
- **Streaming** — Process data as it arrives, not all at once
- **Backpressure** — Slow down producers when consumers can't keep up

---

## Frontend Performance

### Core Web Vitals
- **LCP (Largest Contentful Paint)** — < 2.5s (main content loaded)
- **FID (First Input Delay)** — < 100ms (page is interactive)
- **CLS (Cumulative Layout Shift)** — < 0.1 (visual stability)

### Techniques
- **Code splitting** — Load only what the user needs
- **Lazy loading** — Images, components, routes load on demand
- **Tree shaking** — Remove unused code at build time
- **Image optimization** — WebP, responsive sizes, lazy loading
- **Minimize main thread work** — Offload to web workers where possible

---

## Profiling & Measurement

### Before Optimizing
1. **Profile** — Find the actual bottleneck, not the suspected one
2. **Benchmark** — Measure current performance as a baseline
3. **Hypothesize** — Predict the impact of the optimization
4. **Implement** — Make the change
5. **Verify** — Did it actually help? If not, revert.

### Tools
- **Node.js** — `node --prof`, clinic.js, 0x
- **Python** — cProfile, py-spot, line_profiler
- **Browser** — Chrome DevTools Performance tab, Lighthouse
- **Database** — `EXPLAIN ANALYZE`, `pg_stat_statements`, slow query log
- **System** — `htop`, `iotop`, `netstat`, Prometheus + Grafana

---

## Performance Anti-Patterns

| Anti-Pattern | Why It Hurts |
|---|---|
| **Optimizing without measuring** | You optimize the wrong thing. The real bottleneck remains. |
| **Caching everything** | Cache invalidation nightmares, stale data, memory bloat |
| **Ignoring Big O** | O(n²) with n=1000 is 1M operations. It will always be slow. |
| **Blocking the main thread** | In async systems, synchronous I/O blocks everything |
| **Loading everything at once** | Memory exhaustion, slow startup, poor UX |
| **No connection pooling** | Connection overhead dominates; database chokes |
| **Giant transactions** | Lock contention, timeouts, rollback nightmares |

---

## When Performance Matters

**Always:**
- User-facing response times
- APIs that serve mobile clients
- Batch processing that runs on a schedule

**Sometimes:**
- Internal tools (if used by many people)
- Build times (developer productivity)
- Test suite speed (feedback loop)

**Rarely:**
- One-off scripts
- Prototypes and MVPs (but document the debt)
- Code that's not on the critical path

**Measure. Then optimize. Then measure again.**
