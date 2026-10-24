"""
FastAPI Server — REST API for the Nucleus AI chatbot.

Endpoints:
  POST /api/chat     — Ask a question, get a grounded answer with sources
  GET  /api/health   — Health check
  GET  /api/stats    — Knowledge base statistics
  GET  /             — Serve the frontend (static files)
"""

import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

load_dotenv()

# --- Request/Response Models ---


class ChatRequest(BaseModel):
    """Student's question."""
    question: str = Field(
        ...,
        min_length=2,
        max_length=1000,
        description="The student's question",
        examples=["How do I enrol in courses?"],
    )


class SourceInfo(BaseModel):
    """A source reference."""
    url: str
    title: str


class ChatResponse(BaseModel):
    """AI-generated answer with sources."""
    answer: str
    sources: list[SourceInfo]
    chunks_used: int
    response_time_ms: int


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    llm_provider: str
    knowledge_base_size: int
    detail: str = ""  # What's wrong, when status is "degraded"


class StatsResponse(BaseModel):
    """Knowledge base statistics."""
    total_chunks: int
    sample_urls: list[str]


# --- App Lifecycle ---

# Set up on startup. If the LLM can't be reached then (missing or bad key,
# rate limit, network), a later question retries instead of the server
# staying broken until it restarts.
retriever = None
rag_chain = None
init_error = "Starting up"
LLM_RETRY_SECONDS = 30
_last_llm_attempt = 0.0


def get_rag_chain():
    """Return the RAG chain, connecting to the LLM if that hasn't worked yet."""
    global rag_chain, init_error, _last_llm_attempt
    if (
        rag_chain is None
        and retriever is not None
        and time.time() - _last_llm_attempt >= LLM_RETRY_SECONDS
    ):
        _last_llm_attempt = time.time()
        try:
            from backend.chain import RAGChain
            rag_chain = RAGChain(retriever=retriever)
            init_error = ""
            print("✅ RAG chain initialized successfully!")
        except Exception as e:
            init_error = str(e).splitlines()[0]
            print(f"⚠️  Could not connect to the LLM: {e}")
    return rag_chain


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load the knowledge base and connect to the LLM when the server starts."""
    global retriever, init_error
    print("\n🚀 Starting Nucleus AI server...")
    try:
        # Fetch the prebuilt index (INDEX_URL) if none exists locally
        from backend.index_bundle import ensure_index
        ensure_index()

        from backend.retriever import HybridRetriever
        retriever = HybridRetriever()
    except Exception as e:
        init_error = f"Knowledge base not loaded: {e}"
        print(f"⚠️  {init_error}")
        print("   The server will start, but /api/chat won't work.")
    get_rag_chain()
    yield
    print("\n🛑 Shutting down Nucleus AI server.")


# --- App ---

app = FastAPI(
    title="Nucleus AI",
    description="UNSW Student Hub AI Assistant — grounded answers with source citations",
    version="1.0.0",
    lifespan=lifespan,
)

# --- CORS ---
cors_origins = os.getenv(
    "CORS_ORIGINS",
    "http://localhost:3000,http://localhost:5500,http://127.0.0.1:5500",
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins + ["*"],  # Allow all for development
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- API Endpoints ---


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    Answer a student's question using the RAG pipeline.

    The answer is grounded in UNSW's official website content, with
    inline citations and links to the services it mentions.
    """
    chain = get_rag_chain()
    if chain is None:
        print(f"⚠️  /api/chat unavailable: {init_error}")
        raise HTTPException(
            status_code=503,
            detail="The assistant isn't available right now. Please try again in a minute.",
        )

    start = time.time()

    try:
        result = chain.ask(request.question)
    except Exception as e:
        print(f"⚠️  Error generating response: {e}")
        raise HTTPException(
            status_code=503,
            detail="I couldn't generate an answer right now. Please try again in a minute.",
        )

    elapsed_ms = int((time.time() - start) * 1000)

    return ChatResponse(
        answer=result["answer"],
        sources=[SourceInfo(**s) for s in result["sources"]],
        chunks_used=result["chunks_used"],
        response_time_ms=elapsed_ms,
    )


@app.get("/api/health", response_model=HealthResponse)
async def health():
    """Health check — verify the server and RAG chain are running."""
    kb_size = 0
    if retriever:
        try:
            kb_size = retriever.vector_store.collection.count()
        except Exception:
            pass

    return HealthResponse(
        status="ok" if rag_chain else "degraded",
        llm_provider=type(rag_chain.llm).__name__ if rag_chain else "not initialized",
        knowledge_base_size=kb_size,
        detail="" if rag_chain else init_error,
    )


@app.get("/api/stats", response_model=StatsResponse)
async def stats():
    """Get knowledge base statistics."""
    if retriever is None:
        return StatsResponse(total_chunks=0, sample_urls=[])

    try:
        store_stats = retriever.vector_store.get_stats()
        return StatsResponse(
            total_chunks=store_stats["total_chunks"],
            sample_urls=store_stats["sample_urls"],
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- Serve Frontend ---

frontend_dir = Path(__file__).parent.parent / "frontend"

if frontend_dir.exists():
    @app.get("/")
    async def serve_frontend():
        """Serve the main frontend page."""
        index_path = frontend_dir / "index.html"
        if index_path.exists():
            return FileResponse(index_path)
        raise HTTPException(status_code=404, detail="Frontend not found")

    # Serve static assets (CSS, JS)
    app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")


# --- Run ---

def start_server():
    """Start the server with uvicorn."""
    import uvicorn

    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", "8000"))

    print(f"\n🌐 Starting server at http://{host}:{port}")
    print(f"   Frontend: http://localhost:{port}")
    print(f"   API Docs: http://localhost:{port}/docs")

    uvicorn.run(
        "backend.server:app",
        host=host,
        port=port,
        reload=True,
    )


if __name__ == "__main__":
    start_server()
