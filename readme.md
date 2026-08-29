# 🎥 YouTube Deep Search & Analysis

A powerful tool to perform deep research on YouTube videos by bypassing the standard recommendation algorithm. Search for videos, extract transcripts, and use an LLM (Large Language Model) to analyze the content and answer specific questions — all through a modern web UI or the command line.

## 🚀 Why this tool?

The standard YouTube search engine prioritizes engagement and often limits the results you see. It gives you little control over the search parameters.

**This tool allows you to:**
- **Bypass Recommendations:** Get a comprehensive list of video URLs based on your specific keywords.
- **Deep Content Analysis:** Automatically extract transcripts from hundreds of videos.
- **LLM-Powered Insights:** Use AI to determine if a video covers your topic in depth without watching it.
- **Ranked Shortlist:** Generate a curated list of videos that actually matter to your research.

## ✨ Features

- **Modern Web UI** — A sleek, refined dark **Next.js** frontend for searching, analyzing, and chatting with video data.
- **One-command launcher** — `./start.sh` boots both the backend and frontend together and stops both on `Ctrl+C`.
- **REST API** — FastAPI backend handling search, transcript download, chunking, RAG indexing, and chat — all in one request.
- **Advanced Search** — Filter by language, date range (days/weeks), and exact keywords.
- **Transcript Extraction** — Downloads transcripts using `yt-dlp` (more reliable) or YouTube API.
- **Smart Chunking** — Splits long transcripts into LLM-friendly, overlapping chunks.
- **RAG (Retrieval-Augmented Generation)** — Chat with your video data using OpenAI and ChromaDB.
- **Automatic Indexing** — A ChromaDB collection is built automatically after each analysis.
- **Grounded answers** — The LLM answers only from the retrieved transcript context, so out-of-scope questions return a clear "not found" rather than a made-up answer. Summary-style questions ("summarize this video") are handled specially.
- **Dataset Management** — Delete processed datasets and their ChromaDB indexes directly from the UI.
- **CSV Export** — Automatically saves all found video URLs for easy access.

## 🛠️ Setup

### 1. Backend

Create a virtual environment and install the Python dependencies. **Use `myenv` (Python 3.12)** — the older `venv/` (Python 3.9) contains incompatible package versions (a `transformers`/`tokenizers` mismatch) and will fail to start.

```bash
python3 -m venv myenv
./myenv/bin/pip install -r requirements.txt
```

### 2. API keys

Create a `.env.local` file in the project root and add your keys:

```env
YOUTUBE_API_KEY=your_youtube_api_key
OPENAI_API_KEY=your_openai_api_key
```

> ⚠️ **Important (YouTube):** The **YouTube Data API v3** must be **enabled** for the Google Cloud project that owns the key, and the key must be valid (and ideally restricted to that API). If search returns *"No videos found from YouTube Search."*, the key is being rejected — see [Troubleshooting](#troubleshooting).

### 3. Frontend

```bash
cd frontend/ui
pnpm install
```

## 🚀 How to Start the App

### Method A (recommended) — one command

```bash
./start.sh
```

This starts the **backend** (`./myenv/bin/python api.py` on port 8000) and the **frontend** (`pnpm dev` in `frontend/ui` on port 3000) together, waits for the backend to be ready, and stops **both** when you press `Ctrl+C`. It also clears any stale processes already on ports 8000/3000 first.

Open **http://localhost:3000** in your browser. All `/api` requests are proxied to the backend automatically via a Next.js API route handler (`frontend/ui/app/api/[...path]/route.ts`) with a 10-minute timeout, so long operations like Analyze don't get cut off.

### Method B — two terminals

```bash
# Terminal 1 — backend
./myenv/bin/python api.py          # http://127.0.0.1:8000

# Terminal 2 — frontend
cd frontend/ui
pnpm dev                           # http://localhost:3000
```

## 🔍 How the App Works

1. **Search** — `POST /api/search` uses the YouTube Data API to find videos for your keyword (filtered by language / date).
2. **Analyze** — Clicking **Analyze** on a video calls `POST /api/analyze`, which downloads the transcript (via `yt-dlp` with several fallback strategies), chunks it, and indexes it into a per-video ChromaDB collection.
3. **Chat** — `POST /api/chat` embeds your question, retrieves the most relevant chunks from that video's collection, and asks the LLM to answer **only from** those chunks (citing sources).

### RAG & grounding notes
- The relevance guard short-circuits clearly off-topic questions with *"I could not find any relevant information…"* instead of letting the model guess.
- Summary / meta-questions ("summarize this video", "what is this video about?") bypass the strict distance filter, since the collection is scoped to a single video.
- The OpenAI call uses the model **`gpt-5-mini`** — confirm it is valid for your OpenAI account (note: this model only supports `temperature=1`).

## 📖 CLI Usage Workflow

If you prefer the command line, you can use the individual scripts:

### Step 1: Search & Download Transcripts
Use `LLM_ready_YT_DLP.py` to search for videos and download their transcripts.

```bash
# Search for English videos in the last 3 weeks
python LLM_ready_YT_DLP.py -k "your search query" -l "en" -m 50 -w 3

# Search for Russian videos
python LLM_ready_YT_DLP.py -k "депорт украинцев из сша" -l "ru" -m 10
```

**Arguments:**
- `-k`: Search keyword (required)
- `-l`: Language code (default: `"en"`)
- `-m`: Max videos to process (default: `50`)
- `-w`: Weeks back to search
- `-d`: Days back to search

**Output:**
- A JSONL file in `llm_data/` containing transcripts.
- `video_urls.csv` containing all found video URLs.

### Step 2: Chunk Data
Prepare the transcripts for the LLM by chunking them.

```bash
python chunk_processor.py
```
*The script will prompt you for the input file path (e.g., `llm_data/your_file.jsonl`).*

**Output:** a chunked JSONL file in the `OUTPUT/` directory.

### Step 3: Chat with Data (RAG)
Use the RAG processor to chat with your video data.

```bash
python rag_processor.py --file OUTPUT/your_file_chunked.jsonl
```
*The script will automatically create/load a ChromaDB collection based on the filename.*

## 📂 File Structure

- **`start.sh`** — One-command launcher for the backend + frontend.
- **`api.py`** — FastAPI backend with endpoints for search, analyze, chat, and dataset management.
- **`LLM_ready_YT_DLP.py`** — Main script for searching and downloading transcripts (Recommended).
- **`chunk_processor.py`** — Splits transcripts into smaller chunks for the LLM.
- **`rag_processor.py`** — Indexes chunks into ChromaDB and handles the RAG chat/grounding logic.
- **`LLM_ready.py`** — Legacy script using YouTube API for transcripts (less reliable).
- **`export_urls.py`** — Exports video URLs to CSV.
- **`logger.py`** — Centralized logging (console + rotating `logs/app.log`).
- **`requirements.txt`** — Python project dependencies.
- **`.env.local`** — API keys configuration.
- **`frontend/ui/`** — Next.js frontend application.
  - `app/page.tsx` — Main app component (search console + chat view, datasets sidebar).
  - `app/globals.css` — New design system / styling.
  - `app/api/[...path]/route.ts` — Proxies `/api` to the backend (long timeout).
  - `next.config.mjs` — Next.js config.

## 🛠️ Troubleshooting

- **"Backend returned empty response (HTTP 502)"** — the backend isn't running. Start it with `./start.sh` (or `./myenv/bin/python api.py`).
- **Search returns "No videos found from YouTube Search."** — the YouTube Data API key is invalid or **YouTube Data API v3 isn't enabled** for the project. Enable the API / create a fresh key (and restart the backend afterward).
- **`address already in use` on port 8000** — a stale backend is still bound to the port. The launcher clears it automatically, or run `lsof -ti tcp:8000 | xargs kill -9`.
- **Startup crash with `ImportError` (tokenizers/transformers)** — you launched with the wrong interpreter. Use `./myenv/bin/python api.py`, not `venv`.
- **Chat returns an OpenAI error** — verify the `OPENAI_API_KEY` and that the model id (`gpt-5-mini`) is valid for your account.
