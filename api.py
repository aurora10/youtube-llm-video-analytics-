import os
import json
import re
import subprocess
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List

# Import existing logic
from LLM_ready_YT_DLP import search_videos, download_transcript_ytdlp, clean_filename, BASE_OUTPUT_FOLDER, generate_csv
from chunk_processor import chunk_text, MAX_WORDS_PER_CHUNK, OVERLAP_WORDS, OUTPUT_FOLDER
from rag_processor import build_or_load_index, query_rag_system, client as chroma_client

from logger import get_logger

logger = get_logger("api")

app = FastAPI(title="YouTube Deep Search API")

# Allow CORS for local Vite development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class SearchRequest(BaseModel):
    keyword: str
    lang: str = "en"
    max_videos: int = 5
    days: Optional[int] = None
    weeks: Optional[int] = None
    published_after: Optional[str] = None
    published_before: Optional[str] = None

class ChatRequest(BaseModel):
    query: str
    filename: str
    collection_name: Optional[str] = None

class AnalyzeRequest(BaseModel):
    video_id: str
    title: str = ""
    lang: str = "en"

@app.get("/api/logs")
async def get_logs(lines: int = Query(default=100, ge=1, le=5000)):
    """
    Returns the last N lines from the application log file.
    Useful for debugging from the frontend without SSH access.
    """
    log_path = os.path.join("logs", "app.log")
    if not os.path.exists(log_path):
        return {"lines": [], "message": "No log file found yet."}

    try:
        # Use tail for efficiency on large files
        result = subprocess.run(
            ["tail", "-n", str(lines), log_path],
            capture_output=True,
            text=True,
            timeout=5,
        )
        log_lines = result.stdout.strip().split("\n") if result.stdout.strip() else []
        return {"lines": log_lines, "count": len(log_lines)}
    except Exception as e:
        logger.exception("Failed to read log file")
        raise HTTPException(status_code=500, detail=f"Failed to read logs: {e}")


@app.get("/api/videos")
async def get_videos():
    """Returns a list of processed JSONL files in the output directory."""
    if not os.path.exists(OUTPUT_FOLDER):
        return {"files": []}
    files = [f for f in os.listdir(OUTPUT_FOLDER) if f.endswith(".jsonl")]
    
    # Extract some metadata if possible
    videos = []
    for f in files:
        videos.append({
            "filename": f,
            "name": f.replace("_chunked.jsonl", "").replace(".jsonl", ""),
            "status": "Ready"
        })
    return {"videos": videos}

@app.post("/api/search")
async def api_search(req: SearchRequest):
    """Searches for videos and returns metadata only (no transcript download)."""
    try:
        # Determine lookback days
        lookback_days = 60
        if req.days is not None:
            lookback_days = req.days
        elif req.weeks is not None:
            lookback_days = req.weeks * 7

        video_data_list = search_videos(
            keyword=req.keyword,
            max_results=req.max_videos,
            language=req.lang,
            days=lookback_days,
            published_after=req.published_after,
            published_before=req.published_before
        )

        if not video_data_list:
            raise HTTPException(status_code=404, detail="No videos found from YouTube Search.")

        video_details = []
        for video_info in video_data_list:
            video_details.append({
                "video_id": video_info['video_id'],
                "title": video_info.get("title", "N/A")[:120],
                "thumbnail_url": video_info.get("thumbnail_url", ""),
                "published_date": video_info.get("published_date", "N/A"),
            })

        logger.info(
            "Search completed: keyword='%s', found=%d videos",
            req.keyword, len(video_data_list),
        )
        return {
            "status": "success",
            "videos_found": len(video_data_list),
            "keyword": req.keyword,
            "lang": req.lang,
            "video_details": video_details,
        }

    except HTTPException:
        # Re-raise 4xx errors (e.g. "No videos found") cleanly instead of
        # letting the generic handler rewrap them as a 500 with a mangled detail.
        raise
    except Exception as e:
        logger.exception("Search failed: keyword=%s", req.keyword)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/analyze")
async def api_analyze(req: AnalyzeRequest):
    """Downloads transcript for a single video, chunks it, and indexes into ChromaDB."""
    try:
        # 1. Download transcript
        status, transcript_text, actual_lang, error_detail = download_transcript_ytdlp(req.video_id, req.lang)

        if status != 'success' or not transcript_text:
            friendly_reason = error_detail or "No transcript available for this video"
            return {
                "status": "failed",
                "video_id": req.video_id,
                "detail": friendly_reason,
                "transcript_status": status,
            }

        # 2. Chunk the transcript
        chunks = chunk_text(transcript_text, MAX_WORDS_PER_CHUNK, OVERLAP_WORDS)

        # 3. Build ChromaDB collection name (kept in sync with delete_video)
        collection_name = clean_filename(f"{req.video_id}_{req.lang}")[:63]
        if len(collection_name) < 3:
            collection_name = f"collection_{collection_name}".ljust(3, '_')

        # 4. Save chunked data (embed collection_name so delete_video can find it)
        os.makedirs(OUTPUT_FOLDER, exist_ok=True)
        safe_title = clean_filename(req.title or req.video_id)
        chunked_filename = f"{safe_title}_{req.video_id}_chunked.jsonl"
        chunked_filepath = os.path.join(OUTPUT_FOLDER, chunked_filename)

        with open(chunked_filepath, 'w', encoding='utf-8') as outfile:
            for i, chunk_content in enumerate(chunks):
                entry = {
                    "video_id": req.video_id,
                    "search_keyword": req.title or req.video_id,
                    "search_language": req.lang,
                    "title": req.title or "N/A",
                    "published_date": "N/A",
                    "transcript_language": actual_lang if actual_lang else req.lang,
                    "collection_name": collection_name,
                    "chunk_id": i + 1,
                    "total_chunks": len(chunks),
                    "chunk_text": chunk_content,
                }
                json.dump(entry, outfile, ensure_ascii=False)
                outfile.write('\n')

        # 5. Build ChromaDB index
        build_or_load_index(chunked_filepath, collection_name)

        logger.info(
            "Analyze completed: video_id=%s, chunks=%d, collection=%s",
            req.video_id, len(chunks), collection_name,
        )
        return {
            "status": "success",
            "video_id": req.video_id,
            "title": req.title,
            "chunks_count": len(chunks),
            "transcript_language": actual_lang if actual_lang else req.lang,
            "collection_name": collection_name,
            "filename": chunked_filename,
        }

    except Exception as e:
        logger.exception("Analyze failed: video_id=%s", req.video_id)
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/videos/{filename}")
async def delete_video(filename: str):
    """Deletes a processed dataset: chunked file, raw file, and ChromaDB collection."""
    try:
        # 1. Delete chunked file from OUTPUT folder, capturing the collection
        # name embedded during /api/analyze so its ChromaDB index can be removed.
        chunked_path = os.path.join(OUTPUT_FOLDER, filename)
        collection_name = None
        if os.path.exists(chunked_path):
            try:
                with open(chunked_path, 'r', encoding='utf-8') as cf:
                    first_line = cf.readline()
                embedded = json.loads(first_line).get("collection_name")
                if embedded:
                    collection_name = embedded
            except Exception:
                pass
            os.remove(chunked_path)

        # 2. Derive raw filename (remove _chunked suffix) and delete from llm_data
        raw_filename = filename.replace("_chunked.jsonl", ".jsonl")
        # Also try without .jsonl variants
        base_name = filename.replace("_chunked.jsonl", "")
        raw_path = os.path.join(BASE_OUTPUT_FOLDER, raw_filename)
        if os.path.exists(raw_path):
            os.remove(raw_path)
        else:
            # Fallback: search for matching raw file in llm_data
            if os.path.exists(BASE_OUTPUT_FOLDER):
                for f in os.listdir(BASE_OUTPUT_FOLDER):
                    if f.startswith(base_name) or base_name in f:
                        os.remove(os.path.join(BASE_OUTPUT_FOLDER, f))
                        break

        # 3. Delete ChromaDB collection. Prefer the embedded name captured
        # above; fall back to the legacy derivation from the chunked base name.
        if not collection_name:
            collection_name = base_name[:63]
            if len(collection_name) < 3:
                collection_name = f"collection_{collection_name}".ljust(3, "_")

        try:
            chroma_client.delete_collection(collection_name)
        except Exception:
            # Collection might not exist — that's fine
            pass

        return {"status": "deleted", "filename": filename}
    except Exception as e:
        logger.exception("Delete failed: filename=%s", filename)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/chat")
async def api_chat(req: ChatRequest):
    """Queries the RAG system."""
    try:
        # Use explicit collection_name if provided, otherwise derive from filename
        if req.collection_name:
            collection_name = req.collection_name
        else:
            base_name = os.path.basename(req.filename)
            name_without_ext = base_name.replace(".jsonl", "").replace("_chunked", "")
            sanitized_name = re.sub(r'[^a-zA-Z0-9_.-]', '_', name_without_ext)
            sanitized_name = re.sub(r'^[^a-zA-Z0-9]+', '', sanitized_name)
            sanitized_name = re.sub(r'[^a-zA-Z0-9]+$', '', sanitized_name)
            collection_name = sanitized_name[:63]
            if len(collection_name) < 3:
                 collection_name = f"collection_{collection_name}".ljust(3, '_')

        collection = chroma_client.get_or_create_collection(name=collection_name)
        
        if collection.count() == 0:
            filepath = os.path.join(OUTPUT_FOLDER, req.filename)
            collection = build_or_load_index(filepath, collection_name)

        if collection is None:
            raise HTTPException(
                status_code=404,
                detail=f"No indexed transcript found for '{req.filename}'."
            )

        answer, sources = query_rag_system(req.query, collection)
        
        logger.info("Chat query: filename=%s, query='%s'", req.filename, req.query[:100])
        return {
            "answer": answer,
            "sources": sources
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Chat failed: filename=%s, query='%s'", req.filename, req.query[:100])
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
