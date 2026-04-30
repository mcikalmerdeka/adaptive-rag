# Tech Stack

Current knowledge as of 2026. I know what's production-proven, what's hype, and what tradeoffs each choice carries.

---

## Languages

| Language | Strength | When I Reach For It |
|---|---|---|
| **TypeScript** | Type safety, ecosystem, tooling | Frontend, Node backends, full-stack |
| **Python** | ML/AI ecosystem, scripting, data | ML pipelines, APIs, automation |
| **Go** | Performance, concurrency, simple deployment | High-throughput services, CLIs, platform tooling |
| **Rust** | Memory safety, systems performance | Performance-critical components, WebAssembly targets |
| **SQL** | Relational data, analytics | Anytime a relational DB is in the stack |

---

## Frontend

### Core
- **React 19 / Next.js 15** — Default choice for production web apps; App Router, Server Components, streaming
- **TypeScript** — Non-negotiable for any production frontend
- **Tailwind CSS v4** — Utility-first; fast iteration; pairs well with component libraries
- **shadcn/ui** — Accessible, unstyled-first components; copy-paste model beats black-box libs

### State & Data
- **Zustand** — Lightweight client state; prefer over Redux for most apps
- **TanStack Query (React Query v5)** — Server state, caching, background sync
- **Zod** — Runtime schema validation; use at API boundaries and form inputs

### Testing
- **Vitest** — Fast unit/integration testing; Vite-native
- **Playwright** — E2E testing; cross-browser; better than Cypress for modern apps
- **React Testing Library** — Component testing focused on user behavior, not internals

### Build / Tooling
- **Vite** — Dev server and bundling for non-Next projects
- **Biome** — Fast linter + formatter (replaces ESLint + Prettier in many setups)
- **Turborepo** — Monorepo build orchestration

---

## Backend

### Node.js / TypeScript
- **Hono** — Lightweight, edge-compatible, fast; preferred over Express for new projects
- **Fastify** — High-performance Node HTTP framework when more features needed
- **tRPC** — End-to-end type-safe APIs in full-stack TypeScript monorepos
- **Prisma / Drizzle ORM** — Prisma for developer ergonomics; Drizzle for performance/edge

### Python
- **FastAPI** — Default Python API framework; async, type-annotated, auto-docs
- **Pydantic v2** — Data validation and settings management; use throughout
- **SQLAlchemy 2.x** — ORM for complex relational data access
- **uv** — Fast Python package manager; preferred over pip/poetry in 2026
- **Ruff** — Python linter + formatter; replaces flake8, black, isort

### Authentication
- **Clerk / Auth.js (NextAuth v5)** — For hosted auth in web apps
- **JWT + refresh tokens** — For custom auth in API-first architectures
- **OAuth 2.0 / OIDC** — Standard; know the flows, don't roll your own

---

## Databases

### Relational
- **PostgreSQL** — Default relational database; battle-tested, extensions ecosystem
- **Neon** — Serverless Postgres; preferred for projects needing scale-to-zero (avoids Supabase pausing)
- **PlanetScale / Turso** — MySQL-compatible (PlanetScale) or SQLite-edge (Turso) alternatives

### Caching & Queues
- **Redis / Valkey** — Caching, pub/sub, session storage, rate limiting
- **BullMQ** — Job queue on top of Redis for Node.js

### Document / NoSQL
- **MongoDB** — When document model genuinely fits; don't use as a schema-free escape hatch
- **DynamoDB** — When you need AWS-native key-value at massive scale

### Vector Databases (AI workloads)
- **pgvector** — Start here: Postgres extension for embeddings; zero new infra
- **Pinecone** — Managed, production-grade; when pgvector hits limits
- **Weaviate** — Self-hostable, good for hybrid search (keyword + semantic)
- **Qdrant** — High-performance, Rust-native; strong for on-prem deployments

---

## AI / ML Stack

### LLM APIs & SDKs
- **Anthropic Claude API** — claude-opus-4, claude-sonnet-4 (flagship reasoning and speed)
- **OpenAI API** — GPT-4o, o3/o4-mini for reasoning tasks
- **Google Gemini** — gemini-2.5-pro for long context and multimodal
- **Vercel AI SDK** — Unified SDK for streaming, tool use, multi-provider support in JS/TS
- **LiteLLM** — Provider-agnostic proxy; enables model switching without code changes

### Orchestration & Agents
- **LangChain (LCEL v0.9+)** — Pipeline orchestration; use for composability
- **LlamaIndex v1.2** — Knowledge retrieval layer; RAG pipelines, document parsing
- **LangGraph** — Stateful multi-agent workflows; preferred for complex agent loops
- **MCP (Model Context Protocol)** — De facto standard for agent ↔ tool connectivity; Anthropic-originated, now Linux Foundation; 97M monthly SDK downloads as of Feb 2026

### Embeddings & Retrieval
- **text-embedding-3-large** (OpenAI) or **voyage-3** (Anthropic) — Production embedding models
- **Hybrid search** — BM25 (keyword) + dense vector; almost always outperforms pure semantic

### Document Parsing (for RAG)
- **Docling** — Strong structured doc parsing (PDF, DOCX, tables)
- **MinerU** — PDF extraction with layout understanding
- **Unstructured.io** — General-purpose document ingestion pipeline

### LLM Observability
- **Langfuse** — Open-source LLM observability; traces, evals, cost tracking; self-hostable
- **LangSmith** — LangChain-native tracing and eval platform
- **OpenTelemetry** — Standard instrumentation; use for integrating LLM traces into existing observability stack

### MLOps / Training
- **MLflow** — Experiment tracking, model registry, deployment; most widely adopted open-source
- **Weights & Biases** — Richer experiment tracking for deep learning workflows
- **Hugging Face Hub** — Model hosting, datasets, Spaces for demos
- **Gradio** — Fastest path to an ML demo UI; pairs with HF Inference API
- **PyTorch 2.x** — Default framework for ML model work; 55%+ production share
- **vLLM** — High-throughput LLM inference server; PagedAttention; production serving
- **Airflow / Prefect** — Pipeline orchestration for ML workflows; Airflow for proven stability, Prefect for modern DX

---

## Infrastructure & DevOps

### Containers & Orchestration
- **Docker** — Standard containerization; multi-stage builds; use `uv` for Python images
- **Kubernetes (K8s)** — Production orchestration at scale; know Deployments, Services, Ingress, HPA
- **Docker Compose** — Local dev environments and simpler self-hosted production deployments

### Cloud Providers
- **AWS** — Broadest services; ECS/EKS, Lambda, S3, RDS, SageMaker
- **GCP** — Strong for ML/data workloads; Vertex AI, BigQuery, Cloud Run
- **Azure** — Enterprise environments; Azure OpenAI for compliance-sensitive LLM use cases
- **Vercel / Railway / Fly.io** — Deployment platforms for faster iteration cycles

### Infrastructure as Code
- **Terraform** — Standard IaC; provider ecosystem; remote state in S3/GCS
- **Pulumi** — IaC with real programming languages (TypeScript/Python) — good for complex infra logic
- **CDK (AWS)** — AWS-native; prefer if already deep in AWS ecosystem

### CI/CD
- **GitHub Actions** — Default choice; broad ecosystem; free for OSS
- **GitLab CI** — When using GitLab; strong built-in container registry
- Know: artifact caching, matrix builds, environment protection rules, OIDC for cloud auth (no long-lived secrets)

### Observability
- **OpenTelemetry** — Vendor-neutral instrumentation standard; traces, metrics, logs
- **Grafana + Prometheus** — Open-source metrics and dashboards; standard for self-hosted
- **Datadog / New Relic** — Managed observability when budget allows; faster to set up
- **Sentry** — Error tracking; essential for production frontend and backend

### Networking & Security
- **Cloudflare** — CDN, DDoS protection, Workers for edge compute, Zero Trust
- **Nginx / Caddy** — Reverse proxy; Caddy for automatic TLS
- Secrets management: **Vault (HashiCorp)**, AWS Secrets Manager, or Doppler — never hardcode secrets, never commit `.env` to git

---

## Architectural Patterns I Know Well

| Pattern | When It Fits |
|---|---|
| Monolith | Early-stage products; teams under ~8 engineers; fast iteration priority |
| Modular Monolith | Monolith with clear internal boundaries; prepare for extraction later |
| Microservices | Independent deployment needed; team ownership per service; clear domain boundaries |
| Event-driven (Kafka/SQS) | Async processing; decoupled services; audit trails |
| CQRS + Event Sourcing | Complex domains; full audit history required; high read/write asymmetry |
| RAG Pipeline | LLM apps needing domain knowledge; reduces hallucination; more controllable than fine-tuning |
| Agentic Loops (ReAct/MCP) | Multi-step autonomous tasks; tool use; planning required |
| BFF (Backend for Frontend) | When frontend needs aggregated/transformed data; mobile vs. web diverge |

---

## What I Watch Out For (2026 Landscape)

- **MCP adoption** is accelerating; evaluate it before building custom tool-integration layers
- **pgvector first** for new RAG projects; only migrate to a dedicated vector DB when you hit real limits
- **vLLM + self-hosted inference** is viable at mid-scale; evaluate against API costs at ~$500/month
- **LangGraph > LangChain** for anything involving agent state, branching, or loops
- **Biome over ESLint+Prettier** for new TS projects — same rules, 50–100x faster
- **uv over pip/poetry** for Python projects — significantly faster, better lockfiles
- **Neon over Supabase** when inactivity pausing is a problem (portfolio projects, low-traffic apps)