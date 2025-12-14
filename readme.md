# 🎥 YouTube Deep Search & Analysis

A powerful tool to perform deep research on YouTube videos by bypassing the standard recommendation algorithm. This tool allows you to search for videos, extract transcripts, and use an LLM (Large Language Model) to analyze the content and answer specific questions.

## 🚀 Why this tool?

The standard YouTube search engine prioritizes engagement and often limits the results you see. It gives you little control over the search parameters.

**This tool allows you to:**
- **Bypass Recommendations:** Get a comprehensive list of video URLs based on your specific keywords.
- **Deep Content Analysis:** Automatically extract transcripts from hundreds of videos.
- **LLM-Powered Insights:** Use AI to determine if a video covers your topic in depth without watching it.
- **Ranked Shortlist:** Generate a curated list of videos that actually matter to your research.

## ✨ Features

- **Advanced Search:** Filter by language, date range (days/weeks), and exact keywords.
- **Transcript Extraction:** Downloads transcripts using `yt-dlp` (more reliable) or YouTube API.
- **Smart Chunking:** Splits long transcripts into LLM-friendly chunks.
- **RAG (Retrieval-Augmented Generation):** Chat with your video data using OpenAI and ChromaDB.
- **CSV Export:** Automatically saves all found video URLs for easy access.

## 🛠️ Installation

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/aurora10/youtube-llm-video-analytics-.git
    cd youtube-llm-video-analytics-
    ```

2.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

3.  **Set up Environment Variables:**
    Create a `.env.local` file in the root directory and add your API keys:
    ```env
    YOUTUBE_API_KEY=your_youtube_api_key
    OPENAI_API_KEY=your_openai_api_key
    ```

## 📖 Usage Workflow

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
- `-l`: Language code (default: "en")
- `-m`: Max videos to process (default: 50)
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

**Output:**
- A chunked JSONL file in the `OUTPUT/` directory.

### Step 3: Chat with Data (RAG)
Use the RAG processor to chat with your video data.

```bash
python rag_processor.py --file OUTPUT/your_file_chunked.jsonl
```

*The script will automatically create/load a ChromaDB collection based on the filename.*

## 📂 File Structure

- **`LLM_ready_YT_DLP.py`**: Main script for searching and downloading transcripts (Recommended).
- **`chunk_processor.py`**: Splits transcripts into smaller chunks for the LLM.
- **`rag_processor.py`**: Indexes chunks into ChromaDB and handles the chat interface.
- **`LLM_ready.py`**: Legacy script using YouTube API for transcripts (less reliable).
- **`requirements.txt`**: Project dependencies.
- **`.env.local`**: API keys configuration.
