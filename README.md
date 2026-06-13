# 🧠 Nucleus AI — UNSW Student Hub Assistant

> A grounded AI chatbot for UNSW's Nucleus Student Hub that answers student queries using only official UNSW website content — with source citations for every answer.

![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue)
![License: MIT](https://img.shields.io/badge/license-MIT-green)

## ✨ Features

- **Zero Hallucination** — Answers grounded in actual UNSW web content (like NotebookLM)
- **Source Citations** — Every answer links back to the official UNSW page
- **Hybrid Search** — Combines semantic vector search with BM25 keyword matching
- **Free to Run** — Uses Gemini Flash free tier API + local embedding model
- **Beautiful UI** — Modern dark-themed chat interface with UNSW branding

## 🏗️ Architecture

```
Student Question → Hybrid Retrieval → Grounded LLM Prompt → Cited Answer
                   (Vector + BM25)    (Gemini/Ollama)        (with URLs)
```

## 🚀 Quick Start

### 1. Prerequisites

- **Python 3.12+**
- **Gemini API Key** (free from [Google AI Studio](https://aistudio.google.com/apikey))

### 2. Setup

```bash
# Clone the project
cd Nucleus-AI

# Create virtual environment
python -m venv venv
venv\Scripts\activate   # Windows
# source venv/bin/activate  # macOS/Linux

# Install dependencies
pip install -r requirements.txt

# Configure
copy .env.example .env
# Edit .env and add your GEMINI_API_KEY
```

### 3. Build Knowledge Base

```bash
# Step 1: Crawl main UNSW website (takes 30-60 minutes)
python -m scraper.crawler

# Step 2: Crawl the UNSW Handbook — courses & programs (takes 30-60 minutes)
python -m scraper.handbook_crawler
# Or target specific areas: python -m scraper.handbook_crawler COMP MATH ELEC

# Step 3: Chunk all crawled pages (main site + handbook)
python -m scraper.chunker

# Step 4: Embed and index into vector store
python -m backend.vector_store
```

### 4. Start the Server

```bash
python -m backend.server
```

Open [http://localhost:8000](http://localhost:8000) in your browser.

## 📁 Project Structure

```
Nucleus-AI/
├── scraper/
│   ├── crawler.py            # Scrapy spider for main UNSW website
│   ├── handbook_crawler.py   # Specialized spider for handbook.unsw.edu.au
│   ├── chunker.py            # Text splitting (handbook-aware atomic chunking)
│   ├── settings.py           # Crawl config (domains, delays, subject areas)
│   └── refresh.py            # Full pipeline: crawl → chunk → embed
├── backend/
│   ├── embedder.py     # Embedding generation (sentence-transformers)
│   ├── vector_store.py # ChromaDB vector database
│   ├── retriever.py    # Hybrid search (vector + BM25)
│   ├── llm.py          # LLM interface (Gemini Flash / Ollama)
│   ├── chain.py        # RAG chain orchestration
│   └── server.py       # FastAPI REST API
├── frontend/
│   ├── index.html      # Chat interface
│   ├── index.css       # Design system
│   └── index.js        # Chat logic
├── data/               # Generated data (gitignored)
├── requirements.txt
├── .env.example
├── Dockerfile
└── README.md
```

## 💡 LLM Options

| Provider | Cost | Speed | Setup |
|:---|:---|:---|:---|
| **Gemini Flash** (default) | Free (1500 req/day) | Fast | Just add API key |
| **Ollama + Gemma 3** | Free | Medium | Install [Ollama](https://ollama.com), run `ollama pull gemma3:4b` |

To switch providers, change `LLM_PROVIDER` in your `.env` file.

## 🔄 Updating the Knowledge Base

When UNSW updates their website, re-run the pipeline:

```bash
# Full refresh (main site + handbook + chunk + embed)
python -m scraper.refresh

# Handbook only (faster)
python -m scraper.refresh --handbook-only

# Specific subject areas only
python -m scraper.refresh --handbook-only --areas COMP MATH ELEC
```

## 📊 API Endpoints

| Method | Path | Description |
|:---|:---|:---|
| `POST` | `/api/chat` | Ask a question |
| `GET` | `/api/health` | Health check |
| `GET` | `/api/stats` | Knowledge base stats |
| `GET` | `/docs` | Interactive API docs (Swagger) |

## 🐳 Docker

```bash
docker build -t nucleus-ai .
docker run -p 8000:8000 --env-file .env nucleus-ai
```

## ⚖️ License

MIT — Built as a student project for UNSW.
