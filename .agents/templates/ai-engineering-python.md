# AI Engineering with Python — Project Conventions

Context template for Python-based AI/ML engineering projects.

---

## Core Stack

### Language & Runtime
- **Python 3.11+** — Modern Python with improved performance and typing
- **uv** — Fast Python package manager (replaces pip/poetry)
- **Ruff** — Linter and formatter (replaces flake8, black, isort)
- **pyright** or **mypy** — Type checking

### Web Framework
- **FastAPI** — Async, type-annotated, automatic OpenAPI docs
- **Pydantic v2** — Data validation and settings management
- **Uvicorn** — ASGI server with hot reload in dev

### AI/ML Stack
- **LangChain / LangGraph** — LLM orchestration and agent workflows
- **OpenAI SDK / Anthropic SDK** — Direct LLM API access
- **LiteLLM** — Provider-agnostic LLM proxy
- **Hugging Face Transformers** — Open-source model inference
- **ChromaDB / pgvector** — Vector storage for RAG

### Development Tools
- **pytest** — Testing framework
- **pytest-asyncio** — Async test support
- **httpx** — Async HTTP client for testing APIs
- **python-dotenv** — Environment variable management

---

## Project Structure

```
project-root/
├── src/
│   ├── api/                    # FastAPI application
│   │   ├── __init__.py
│   │   ├── main.py            # App entry point
│   │   ├── deps.py            # Dependencies (DB, auth)
│   │   └── routers/           # API route modules
│   │       ├── __init__.py
│   │       ├── chat.py        # Chat/LLM endpoints
│   │       ├── rag.py         # RAG endpoints
│   │       └── health.py      # Health checks
│   ├── core/                   # Core business logic
│   │   ├── __init__.py
│   │   ├── config.py          # Pydantic settings
│   │   ├── exceptions.py      # Custom exceptions
│   │   └── security.py        # Auth utilities
│   ├── services/               # Business services
│   │   ├── __init__.py
│   │   ├── llm/               # LLM-related services
│   │   │   ├── __init__.py
│   │   │   ├── client.py      # LLM client wrapper
│   │   │   ├── chains.py      # LangChain chains
│   │   │   └── agents.py      # Agent definitions
│   │   ├── rag/               # RAG services
│   │   │   ├── __init__.py
│   │   │   ├── embeddings.py  # Embedding generation
│   │   │   ├── retriever.py   # Document retrieval
│   │   │   └── indexer.py     # Document indexing
│   │   └── embeddings/        # Embedding model management
│   ├── models/                 # Pydantic models
│   │   ├── __init__.py
│   │   ├── requests.py        # API request schemas
│   │   ├── responses.py       # API response schemas
│   │   └── domain.py          # Domain models
│   ├── db/                     # Database layer
│   │   ├── __init__.py
│   │   ├── connection.py      # DB connection management
│   │   ├── models.py          # SQLAlchemy/ORM models
│   │   └── repositories.py    # Data access layer
│   └── utils/                  # Utilities
│       ├── __init__.py
│       ├── logging.py         # Logging configuration
│       └── helpers.py         # Helper functions
├── tests/
│   ├── __init__.py
│   ├── conftest.py            # pytest fixtures
│   ├── test_api/              # API/integration tests
│   └── test_services/         # Unit tests
├── scripts/                    # Utility scripts
│   ├── seed_db.py
│   └── index_documents.py
├── notebooks/                  # Jupyter notebooks for exploration
├── docs/                       # Documentation
├── .env                        # Environment variables (gitignored)
├── .env.example               # Example env file
├── pyproject.toml             # Project config and dependencies
├── README.md
└── Dockerfile
```

---

## Development Guidelines

### Configuration (Pydantic Settings)

```python
# src/core/config.py
from pydantic_settings import BaseSettings
from functools import lru_cache

class Settings(BaseSettings):
    app_name: str = "AI API"
    debug: bool = False
    
    # API Keys
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    
    # Database
    database_url: str = "postgresql://localhost/aiapp"
    
    # Vector DB
    vector_db_path: str = "./chroma_db"
    
    class Config:
        env_file = ".env"

@lru_cache
def get_settings() -> Settings:
    return Settings()
```

### FastAPI App Structure

```python
# src/api/main.py
from fastapi import FastAPI
from contextlib import asynccontextmanager

from api.routers import chat, rag, health
from core.config import get_settings

settings = get_settings()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: initialize connections, load models
    yield
    # Shutdown: cleanup

app = FastAPI(
    title=settings.app_name,
    debug=settings.debug,
    lifespan=lifespan
)

app.include_router(health.router, prefix="/health", tags=["health"])
app.include_router(chat.router, prefix="/api/v1/chat", tags=["chat"])
app.include_router(rag.router, prefix="/api/v1/rag", tags=["rag"])
```

### Router Pattern

```python
# src/api/routers/chat.py
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from services.llm.client import LLMClient
from models.requests import ChatRequest
from models.responses import ChatResponse

router = APIRouter()

@router.post("/", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    llm: LLMClient = Depends(get_llm_client)
) -> ChatResponse:
    try:
        response = await llm.generate(
            messages=request.messages,
            model=request.model
        )
        return ChatResponse(content=response.content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

### LLM Client Wrapper

```python
# src/services/llm/client.py
from typing import AsyncGenerator
import openai
from anthropic import AsyncAnthropic

from core.config import get_settings

class LLMClient:
    def __init__(self):
        settings = get_settings()
        self.openai = openai.AsyncOpenAI(api_key=settings.openai_api_key)
        self.anthropic = AsyncAnthropic(api_key=settings.anthropic_api_key)
    
    async def generate(
        self,
        messages: list[dict],
        model: str = "gpt-4",
        stream: bool = False
    ) -> str:
        if model.startswith("claude"):
            return await self._generate_anthropic(messages, model)
        return await self._generate_openai(messages, model)
    
    async def _generate_openai(self, messages, model):
        response = await self.openai.chat.completions.create(
            model=model,
            messages=messages
        )
        return response.choices[0].message.content
    
    async def stream_generate(
        self,
        messages: list[dict],
        model: str = "gpt-4"
    ) -> AsyncGenerator[str, None]:
        stream = await self.openai.chat.completions.create(
            model=model,
            messages=messages,
            stream=True
        )
        async for chunk in stream:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

def get_llm_client() -> LLMClient:
    return LLMClient()
```

### RAG Pattern with ChromaDB

```python
# src/services/rag/retriever.py
import chromadb
from chromadb.config import Settings

from core.config import get_settings

class RAGRetriever:
    def __init__(self):
        settings = get_settings()
        self.client = chromadb.PersistentClient(
            path=settings.vector_db_path,
            settings=Settings(anonymized_telemetry=False)
        )
        self.collection = self.client.get_or_create_collection("documents")
    
    async def add_documents(
        self,
        documents: list[str],
        embeddings: list[list[float]],
        ids: list[str],
        metadatas: list[dict] | None = None
    ):
        self.collection.add(
            documents=documents,
            embeddings=embeddings,
            ids=ids,
            metadatas=metadatas
        )
    
    async def query(
        self,
        query_embedding: list[float],
        n_results: int = 5
    ) -> list[dict]:
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results
        )
        return [
            {
                "document": doc,
                "metadata": meta,
                "distance": dist
            }
            for doc, meta, dist in zip(
                results["documents"][0],
                results["metadatas"][0],
                results["distances"][0]
            )
        ]
```

---

## Testing Patterns

### pytest Configuration

```toml
# pyproject.toml
[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
python_functions = ["test_*"]
addopts = "-v --tb=short"
asyncio_mode = "auto"
```

### Test Fixtures

```python
# tests/conftest.py
import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient

from api.main import app

@pytest.fixture
def client():
    return TestClient(app)

@pytest.fixture
async def async_client():
    async with AsyncClient(app=app, base_url="http://test") as client:
        yield client

@pytest.fixture
def mock_llm_response():
    return {
        "content": "Test response",
        "model": "gpt-4",
        "usage": {"prompt_tokens": 10, "completion_tokens": 20}
    }
```

### API Tests

```python
# tests/test_api/test_chat.py
import pytest
from unittest.mock import AsyncMock, patch

@pytest.mark.asyncio
async def test_chat_endpoint(async_client, mock_llm_response):
    with patch("services.llm.client.LLMClient.generate", new_callable=AsyncMock) as mock:
        mock.return_value = mock_llm_response
        
        response = await async_client.post("/api/v1/chat/", json={
            "messages": [{"role": "user", "content": "Hello"}],
            "model": "gpt-4"
        })
        
        assert response.status_code == 200
        assert response.json()["content"] == "Test response"
```

---

## Environment Setup

### .env.example

```bash
# App
APP_NAME="AI API"
DEBUG=true

# API Keys
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...

# Database
DATABASE_URL=postgresql://user:pass@localhost/aiapp

# Vector DB
VECTOR_DB_PATH=./chroma_db
```

### pyproject.toml Dependencies

```toml
[project]
name = "ai-engineering-api"
version = "0.1.0"
description = "AI Engineering API"
requires-python = ">=3.11"
dependencies = [
    # Web
    "fastapi>=0.104.0",
    "uvicorn[standard]>=0.24.0",
    "pydantic>=2.0.0",
    "pydantic-settings>=2.0.0",
    
    # AI/ML
    "openai>=1.0.0",
    "anthropic>=0.8.0",
    "langchain>=0.1.0",
    "langgraph>=0.0.40",
    "chromadb>=0.4.0",
    "sentence-transformers>=2.2.0",
    "litellm>=1.0.0",
    
    # Database
    "sqlalchemy>=2.0.0",
    "asyncpg>=0.29.0",
    "alembic>=1.12.0",
    
    # Utils
    "python-dotenv>=1.0.0",
    "structlog>=23.0.0",
    "orjson>=3.9.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.4.0",
    "pytest-asyncio>=0.21.0",
    "httpx>=0.25.0",
    "ruff>=0.1.0",
    "pyright>=1.1.0",
]

[tool.ruff]
line-length = 88
target-version = "py311"
select = ["E", "F", "I", "N", "W", "UP", "B", "C4", "SIM"]
ignore = ["E501"]

[tool.ruff.format]
quote-style = "double"
indent-style = "space"

[tool.pyright]
pythonVersion = "3.11"
strict = ["src"]
```

---

## Docker Setup

```dockerfile
# Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install uv
RUN pip install uv

# Copy dependency files
COPY pyproject.toml ./

# Install dependencies
RUN uv pip install --system -e ".[dev]"

# Copy source
COPY src/ ./src/

# Run
CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

---

## Code Quality Standards

### Ruff Configuration (in pyproject.toml)
- Line length: 88 (Black-compatible)
- Target Python: 3.11+
- Enable: E, F, I (isort), N (pep8-naming), W, UP (pyupgrade), B (flake8-bugbear)

### Type Hints
- Use `|` union syntax (Python 3.10+): `str | None`
- Use built-in generics: `list[str]`, `dict[str, int]`
- Annotate all function signatures
- Use Pydantic models for complex data structures

### Async Patterns
- Use `async`/`await` for all I/O operations
- Prefer `asyncio.gather()` for concurrent operations
- Use `asynccontextmanager` for resource management
- Don't use `asyncio.run()` in FastAPI handlers (already in async context)

### Error Handling
```python
# Custom exceptions
class LLMError(Exception):
    """Base class for LLM-related errors"""
    pass

class RateLimitError(LLMError):
    """API rate limit exceeded"""
    pass

# Usage in services
from fastapi import HTTPException

try:
    result = await llm.generate(messages)
except RateLimitError as e:
    raise HTTPException(status_code=429, detail="Rate limit exceeded")
except LLMError as e:
    logger.error(f"LLM error: {e}")
    raise HTTPException(status_code=502, detail="LLM service error")
```