---
title: Nucleus AI
emoji: ⚛️
colorFrom: yellow
colorTo: gray
sdk: docker
app_port: 7860
short_description: Answers UNSW student questions with cited sources
pinned: false
---

# 🧠 Nucleus AI — UNSW Student Hub Assistant

> A grounded AI chatbot for UNSW's Nucleus Student Hub that answers student queries using only official UNSW website content — with source citations for every answer.

![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue)
![License: MIT](https://img.shields.io/badge/license-MIT-green)

## ✨ Features

- **Zero Hallucination** — Answers grounded in actual UNSW web content (like NotebookLM)
- **Source Citations** — Every answer links back to the official UNSW page
- **Hybrid Search** — Combines semantic vector search with BM25 keyword matching
- **Always Fresh** — A weekly GitHub Actions job re-fetches only the pages UNSW changed
- **No Waiting for Crawls** — The server downloads a prebuilt index on startup
- **Free to Run** — Uses the Gemini Flash-Lite free tier + a local embedding model
- **Beautiful UI** — Modern dark-themed chat interface with UNSW branding

## 🏗️ Architecture

```
Student Question → Hybrid Retrieval → Grounded LLM Prompt → Cited Answer
                   (Vector + BM25)    (Gemini/Ollama)        (with URLs)
```

The knowledge base is built from UNSW's own sitemap:

```
sitemap.xml ─→ /student pages ─→ fetch new/changed ─→ chunk ─→ embed ─→ index-latest release
 (lastmod)      (~500 pages)      (manifest diff)                         (weekly, GitHub Actions)
                                                                                   │
                                          server startup: download if no local index
```

## 🚀 Quick Start

### 1. Prerequisites

- **Python 3.12+** (with the `lzma` module, which Scrapy needs; some pyenv builds lack it)
- **Gemini API Key** (free from [Google AI Studio](https://aistudio.google.com/apikey))

### 2. Setup

```bash
# Clone the project
cd Nucleus-AI

# Create virtual environment
python -m venv venv
source venv/bin/activate    # macOS/Linux
# venv\Scripts\activate     # Windows

# Install dependencies
pip install -r requirements.txt

# Configure
cp .env.example .env        # Windows: copy .env.example .env
# Edit .env and add your GEMINI_API_KEY
```

### 3. Start the Server

```bash
python -m backend.server
```

On first start, the server downloads the prebuilt index from this repo's
[`index-latest` release](https://github.com/Likheet/Nucleus-AI/releases/tag/index-latest)
into `data/`, which takes seconds. No crawling needed.

Open [http://localhost:8000](http://localhost:8000) in your browser.

## 📚 The Knowledge Base

### Where the data comes from

UNSW lists every page in [sitemap.xml](https://www.unsw.edu.au/sitemap.xml)
with a `<lastmod>` date. Nucleus AI indexes the pages under `/student`
(about 500, including fees, key dates, enrolment, support and student life).
To index more, set `SITEMAP_PATHS` in `.env`, e.g.
`SITEMAP_PATHS=/student,/study/how-to-apply/fees`.

Known gap: the date list on the Key dates page (census dates, enrolment
deadlines) is loaded by JavaScript, so it isn't in the index. Term start and
end dates from the Academic calendar page are.

### Build or refresh it yourself

```bash
python -m scraper.refresh
```

One command does everything:

1. Reads the sitemap and picks the `/student` pages
2. Compares each page's `lastmod` with `data/manifest.json`
3. Fetches only new or changed pages, politely: it obeys `robots.txt`, waits
   its `Crawl-delay` (10s on www.unsw.edu.au) between requests, and sends one
   request at a time
4. Re-chunks and re-embeds only pages whose content actually changed, and
   drops pages that left the sitemap

The **first** run fetches every page, which takes about 2 hours: besides the
10s crawl delay, many sitemap URLs redirect two or three times, and each hop
waits too. **Later** runs only fetch what changed: with no sitemap changes a
run takes under a minute, and a typical week's changes take a few minutes.
To stop early, press Ctrl-C **once**: pages fetched so far are indexed and
saved, and the next run fetches the rest.

| Option | What it does |
|:---|:---|
| `--limit N` | Fetch at most N pages this run (later runs fetch the rest) |
| `--rechunk` | Re-chunk and re-embed every stored page, e.g. after changing the chunker (no re-fetching) |

What ends up in `data/` (git-ignored):

| Path | Contents |
|:---|:---|
| `manifest.json` | URL, `lastmod`, content hash and fetch time of every indexed page |
| `raw/all_pages.jsonl` | Extracted page content |
| `raw/handbook_pages.jsonl` | Handbook courses and programs (optional, see below) |
| `chunks/all_chunks.jsonl` | Chunks (also used for BM25 keyword search) |
| `chroma_db/` | ChromaDB vector store |

### UNSW Handbook (optional)

The Handbook crawler is a separate, optional step and is **not** part of the
weekly build. It reads the Handbook's own
[sitemap index](https://www.handbook.unsw.edu.au/sitemap.xml), picks the
course and program pages for `HANDBOOK_YEAR` (default `2026`), and writes
`data/raw/handbook_pages.jsonl`, which the next `python -m scraper.refresh`
indexes alongside the sitemap pages:

```bash
python -m scraper.handbook_crawler COMP MATH   # only these subject areas' courses
python -m scraper.handbook_crawler             # every course and program
python -m scraper.refresh
```

- **What it extracts:** each page embeds its data as JSON (`__NEXT_DATA__`),
  so courses get their overview, prerequisites, offering terms, fees, learning
  outcomes, faculty and school, and programs get their overview, structure
  and entry requirements. Courses are listed under both undergraduate and
  postgraduate, so `COMP` is 181 pages for 132 course codes.
- **Incremental:** each page's sitemap `lastmod` is stored with it, and later
  runs fetch only new or changed pages (the Handbook publishes daily
  incremental sitemaps). Ctrl-C **once** keeps what was fetched so far.
- **Each run matches what you ask for:** pages outside the requested subject
  areas are dropped from the file (and from the index on the next refresh),
  so pass every area you want each time. A `MATH` run after a `COMP` run
  drops COMP.
- **Speed:** requests are 2 seconds apart (the Handbook's `robots.txt` sets
  no Crawl-delay), about 2.5 seconds per page in practice. `COMP` takes about
  7 minutes; everything for a year (about 6,000 courses and 660 programs)
  takes about 4.5 hours on the first run. A run with nothing new takes a
  couple of seconds.

## 🔄 Automatic Weekly Refresh (GitHub Actions)

[`.github/workflows/build-index.yml`](.github/workflows/build-index.yml) runs
weekly (Sundays 17:00 UTC) and on demand. It downloads the previous index, runs
`python -m scraper.refresh` (so only changed pages are fetched), and uploads
`nucleus-index.tar.gz` to the `index-latest` release, which is where the
server's startup download comes from. Embeddings run on the runner, so the
workflow needs **no API keys**.

To turn it on:

1. Merge this workflow into `main` and push. Scheduled workflows only run
   from the default branch.
2. Go to **Actions → Build index → Run workflow** to run it once by hand.
   The first run does the full ~2-hour crawl and creates the
   `index-latest` release. Runs after that are incremental.
3. Optional: to restart a Hugging Face Space after each build so it picks up
   the new index, add a repository **variable** `HF_SPACE_ID` (e.g.
   `your-name/nucleus-ai`) and a repository **secret** `HF_TOKEN` (a
   Hugging Face access token with write access) under
   **Settings → Secrets and variables → Actions**.

GitHub pauses scheduled workflows in public repos after 60 days without
commits. If that happens, re-enable it from the Actions tab.

## 🌐 Deploy a Live Demo

The Docker image serves the app and downloads the prebuilt index on startup,
so it boots in seconds instead of crawling. Run the workflow once first (see
above) so the `index-latest` release exists.

The app needs about **750 MB of RAM** (PyTorch, the embedding model and the
in-memory keyword index), so choose a host with at least 1 GB. The prebuilt
index download is about 45 MB.

### Option A: Hugging Face Spaces (Docker)

Docker Spaces run on free CPU Basic hardware (2 vCPU, 16 GB), but creating
one requires a [Hugging Face PRO](https://huggingface.co/pricing) account.

1. Sign in at [huggingface.co](https://huggingface.co) and click
   **New Space**. Pick a name (e.g. `nucleus-ai`), choose **Docker** as the
   SDK with the **Blank** template, keep **CPU Basic**, and make it public.
2. In the Space, open **Settings → Variables and secrets → New secret** and
   add `GEMINI_API_KEY` with your key.
3. Create a Hugging Face [access token](https://huggingface.co/settings/tokens)
   with **write** access. You'll use it as the git password.
4. Push this repo to the Space (the YAML block at the top of this README is
   the Space's configuration):

   ```bash
   git remote add space https://huggingface.co/spaces/<your-hf-username>/nucleus-ai
   ```

   ```bash
   git push --force space main
   ```

   `--force` is only needed the first time, to replace the Space's starter
   README.
5. Watch the build under the Space's **Logs** tab. When it shows
   `Application startup complete`, the demo is live at
   `https://<your-hf-username>-nucleus-ai.hf.space`.

Every later `git push space main` rebuilds the Space. Free hardware sleeps
after a period without visitors. The next visit wakes it, and it downloads
the latest index again because Space disks are wiped on restart.

### Option B: Render

1. Sign in at [render.com](https://render.com) and choose
   **New → Web Service**, then connect this GitHub repository.
2. Render detects the `Dockerfile`. Choose the **Standard** instance (2 GB).
   The Free and Starter instances have 512 MB, which isn't enough.
3. Under **Environment**, add `GEMINI_API_KEY`.
4. Click **Create Web Service**. Render sets `PORT` itself and redeploys on
   every push to `main`.

### Run the image locally

```bash
docker build -t nucleus-ai .
```

```bash
docker run -p 7860:7860 --env-file .env nucleus-ai
```

Then open [http://localhost:7860](http://localhost:7860).

## 📁 Project Structure

```
Nucleus-AI/
├── scraper/
│   ├── refresh.py            # One command: sitemap diff → fetch → chunk → embed
│   ├── sitemap.py            # Reads sitemap.xml and robots.txt Crawl-delay
│   ├── crawler.py            # Scrapy spider: fetches pages, extracts content
│   ├── handbook_crawler.py   # Optional spider for handbook.unsw.edu.au
│   ├── chunker.py            # Text splitting (handbook-aware atomic chunking)
│   └── settings.py           # Crawl config (sitemap paths, delays, subject areas)
├── backend/
│   ├── embedder.py      # Embedding generation (sentence-transformers)
│   ├── vector_store.py  # ChromaDB vector database
│   ├── retriever.py     # Hybrid search (vector + BM25)
│   ├── llm.py           # LLM interface (Gemini / Ollama)
│   ├── chain.py         # RAG chain orchestration
│   ├── index_bundle.py  # Packs / downloads the prebuilt index
│   └── server.py        # FastAPI REST API
├── frontend/
│   ├── index.html      # Chat interface
│   ├── index.css       # Design system
│   └── index.js        # Chat logic
├── .github/workflows/
│   └── build-index.yml # Weekly index build → index-latest release
├── data/               # Generated data (gitignored)
├── requirements.txt
├── .env.example
├── Dockerfile
└── README.md
```

## 💡 LLM Options

| Provider | Cost | Speed | Setup |
|:---|:---|:---|:---|
| **Gemini 3.5 Flash-Lite** (default) | Free tier | Fast | Just add API key |
| **Ollama + Gemma 3** | Free | Medium | Install [Ollama](https://ollama.com), run `ollama pull gemma3:4b` |

To switch providers, change `LLM_PROVIDER` in your `.env` file. To use a
different Gemini model, set `GEMINI_MODEL` (Gemini 2.0 Flash was retired in
June 2026).

## ⚙️ Configuration

| Variable | Default | Purpose |
|:---|:---|:---|
| `GEMINI_API_KEY` | | Gemini API key (required for answers) |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` | Gemini model |
| `INDEX_URL` | this repo's `index-latest` asset | Prebuilt index to download when none exists locally (empty = never) |
| `SITEMAP_PATHS` | `/student` | Sitemap path prefixes to index |
| `CRAWL_DELAY` | `1.5` | Minimum seconds between requests (robots.txt's Crawl-delay wins if longer) |

## 📊 API Endpoints

| Method | Path | Description |
|:---|:---|:---|
| `POST` | `/api/chat` | Ask a question |
| `GET` | `/api/health` | Health check |
| `GET` | `/api/stats` | Knowledge base stats |
| `GET` | `/docs` | Interactive API docs (Swagger) |

## ⚖️ License

MIT — Built as a student project for UNSW.
