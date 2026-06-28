import re
import os
import json
import csv
import time
import subprocess
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from datetime import datetime, timedelta
import traceback
import argparse
from dotenv import load_dotenv

from logger import get_logger

logger = get_logger("yt_dlp")

load_dotenv('.env.local')
api_key = os.getenv("YOUTUBE_API_KEY")

# --- Configuration ---
BASE_OUTPUT_FOLDER = "llm_data"
ADD_DELAY_BETWEEN_TRANSCRIPTS = 1 # Seconds (0 to disable)

# --- YouTube Data API Service Initialization (for video search) ---
youtube = None
try:
    if not api_key:
        logger.error("YOUTUBE_API_KEY is missing from .env.local.")
        logger.error("Please add it to your .env.local file if you need video search.")
    else:
        youtube = build("youtube", "v3", developerKey=api_key)
        logger.info("YouTube Data API service initialized successfully (for video search).")
except Exception as e:
    logger.error("Error building YouTube Data API service: %s", e)

# --- Helper Functions ---

def parse_iso8601_duration(duration_str):
    if not duration_str: return 0
    match = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?', duration_str)
    if not match: return 0
    hours = int(match.group(1)) if match.group(1) else 0
    minutes = int(match.group(2)) if match.group(2) else 0
    seconds = float(match.group(3)) if match.group(3) else 0
    return int(hours * 3600 + minutes * 60 + seconds)

def clean_filename(name):
    name = re.sub(r'[\\/*?:"<>|]+', '', name)
    name = re.sub(r'[^\w\-]+', '_', name)
    name = name.strip('_-')
    name = name[:100]
    return name if name else "invalid_keyword"

def cleanup_temp_files():
    """
    Removes any temporary transcript files left over from previous runs.
    """
    count = 0
    for f_name in os.listdir('.'):
        if f_name.startswith("temp_transcript_"):
            try:
                os.remove(f_name)
                count += 1
            except OSError as e:
                logger.warning("Could not remove temp file %s: %s", f_name, e)
    if count > 0:
        logger.info("Cleaned up %d temporary transcript files.", count)

def generate_csv(jsonl_path, current_video_list, csv_output_path="video_urls.csv"):
    """
    Exports video URLs to a CSV file.
    Includes URLs from:
    1. The existing JSONL file (historical successful transcripts).
    2. The current search results (all found videos, including failures).
    """
    all_video_ids = set()

    # 1. Add IDs from the JSONL file (historical)
    if os.path.exists(jsonl_path):
        logger.info("Reading historical IDs from %s...", jsonl_path)
        try:
            with open(jsonl_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line: continue
                    try:
                        data = json.loads(line)
                        if 'video_id' in data:
                            all_video_ids.add(data['video_id'])
                    except json.JSONDecodeError:
                        pass
        except Exception as e:
            logger.error("Error reading JSONL file: %s", e)

    # 2. Add IDs from the current search (all found)
    if current_video_list:
        logger.info("Adding %d IDs from current search...", len(current_video_list))
        for video_info in current_video_list:
            all_video_ids.add(video_info['video_id'])

    if not all_video_ids:
        logger.info("No URLs found to export to CSV.")
        return

    # Convert to URLs
    urls = [[f"https://www.youtube.com/watch?v={vid}"] for vid in all_video_ids]

    logger.info("Generating CSV with %d total URLs...", len(urls))

    try:
        with open(csv_output_path, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(['Video URL']) # Header
            writer.writerows(urls)
        logger.info("Successfully wrote %d URLs to %s", len(urls), csv_output_path)
    except Exception as e:
        logger.error("Error writing to CSV: %s", e)

# --- yt-dlp Transcript Fetch Function (with improved formatting) ---
def _parse_transcript_file(downloaded_file_path, video_id, requested_language_code):
    """
    Internal helper: parse a .json3 transcript file and return (transcript_text, actual_lang).
    """
    import re as _re

    # --- VTT / SRT plain-text parsing (used as fallback) ---
    def _parse_vtt_srt(filepath):
        """Parse plain .vtt or .srt file, return (text, None) or (None, None)."""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                raw = f.read()
        except Exception as exc:
            logger.error("ERROR reading %s: %s", filepath, exc)
            return None, None
        # Remove WEBVTT header
        cleaned = _re.sub(r'^\s*WEBVTT.*\n', '', raw, flags=_re.IGNORECASE | _re.MULTILINE)
        # Remove timestamp lines (00:00:00.000 --> 00:00:00.000 style)
        cleaned = _re.sub(r'\d{2}:\d{2}:\d{2}[.,]\d{2,3}\s*-->\s*\d{2}:\d{2}:\d{2}[.,]\d{2,3}', '', cleaned)
        # Remove cue index numbers (single numbers on their own line)
        cleaned = _re.sub(r'^\d+\s*$', '', cleaned, flags=_re.MULTILINE)
        # Remove SRT-style positioning info
        cleaned = _re.sub(r'^\s*X\d+:\d+\s+Y\d+:\d+\s*$', '', cleaned, flags=_re.MULTILINE)
        # Remove VTT/SRT tags like <c>, </c>, <00:00:01.000>
        cleaned = _re.sub(r'</?[^>]+>', '', cleaned)
        # Remove repeated newlines
        cleaned = _re.sub(r'\n{3,}', '\n\n', cleaned)
        text = cleaned.strip()
        if not text or len(text) < 10:
            return None, None
        text = _re.sub(r' +', ' ', text).strip()
        return text, None

    # If it's a VTT or SRT file, parse as plain text
    if downloaded_file_path.endswith('.vtt') or downloaded_file_path.endswith('.srt'):
        transcript_text, actual_lang = _parse_vtt_srt(downloaded_file_path)
        if transcript_text:
            return transcript_text, requested_language_code
        return None, None

    try:
        actual_lang = requested_language_code
        try:
            actual_lang = downloaded_file_path.split('.')[-2]
        except IndexError:
            pass

        with open(downloaded_file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        event_texts = []
        if "events" in data:
            for event in data["events"]:
                segment_texts_for_event = []
                if "segs" in event:
                    for seg in event["segs"]:
                        if "utf8" in seg:
                            segment_texts_for_event.append(seg["utf8"].strip())
                if segment_texts_for_event:
                    event_texts.append(" ".join(segment_texts_for_event))

        transcript_text_raw = "\n".join(event_texts)
        transcript_text = _re.sub(r' +', ' ', transcript_text_raw).strip()
        return transcript_text, actual_lang
    except json.JSONDecodeError as e:
        logger.error("Failed to parse JSON from transcript file for %s: %s", video_id, e)
        return None, None
    except Exception as e:
        logger.error("Unexpected error parsing transcript for %s: %s", video_id, e)
        return None, None


def _find_transcript_file(base_name):
    """Find any .json3 (or .vtt/.srt) transcript file matching base_name."""
    for f_name in os.listdir('.'):
        if f_name.startswith(base_name) and (f_name.endswith('.json3') or f_name.endswith('.vtt') or f_name.endswith('.srt')):
            return f_name
    return None


def download_transcript_ytdlp(video_id, requested_language_code="en"):
    """
    Downloads transcript for a video ID using yt-dlp (Python module).
    Tries auto-generated subs first, then falls back to manual subs.
    Adds fallback strategies for VTT/SRT formats and player_client=web.

    Args:
        video_id (str): The YouTube video ID.
        requested_language_code (str): The desired language code (e.g., "en", "es").

    Returns:
        tuple: (status, transcript_text, actual_language_code, error_detail)
               status: 'success', 'no_transcript', 'failed_ytdlp', 'error_ytdlp'
               transcript_text: The transcript, or None
               actual_language_code: The language code used, or None
               error_detail: A human-readable error string, or None
    """
    import sys
    import os
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    base_name = f"temp_transcript_{video_id}"

    transcript_text = None
    actual_lang = None
    status = 'no_transcript'
    last_stderr = ""

    # --- Cookies support (env var YTDLP_COOKIES_BROWSER) ---
    cookies_args = []
    cookies_browser = os.getenv("YTDLP_COOKIES_BROWSER")
    if cookies_browser:
        cookies_args = ["--cookies-from-browser", cookies_browser]

    # Cleanup any leftover temp files from previous attempts
    for f_name in list(os.listdir('.')):
        if f_name.startswith(f"temp_transcript_{video_id}"):
            try:
                os.remove(f_name)
            except OSError:
                pass

    def _run_ytdlp(extra_args):
        """Run yt-dlp via Python module with given extra args. Returns (found_file_path, stderr)."""
        cmd = [
            sys.executable, "-m", "yt_dlp",
            video_url,
            "--skip-download",
            "-o", base_name,
            "--no-warnings",
            "--proxy", "",
            "--extractor-args", "youtube:player_client=web",
        ] + cookies_args + extra_args
        try:
            process = subprocess.run(cmd, check=False, capture_output=True, text=True, encoding='utf-8', timeout=60)
            stderr_lower = process.stderr.lower() if process.stderr else ""
            if process.returncode != 0:
                return None, stderr_lower
            found = _find_transcript_file(base_name)
            return found, stderr_lower
        except subprocess.TimeoutExpired:
            return None, "timeout: yt-dlp took longer than 60 seconds"
        except Exception as exc:
            return None, f"error running yt-dlp: {exc}"

    def _clean_temp():
        for f_name in list(os.listdir('.')):
            if f_name.startswith(base_name):
                try: os.remove(f_name)
                except OSError: pass

    # --- Strategy 1: Auto subs with requested language (json3) ---
    logger.debug("[%s] Attempt 1: auto-subs (%s)...", video_id, requested_language_code)
    found_file, last_stderr = _run_ytdlp([
        "--write-auto-subs",
        "--sub-langs", f"{requested_language_code}.*",
        "--sub-format", "json3",
    ])
    if found_file:
        transcript_text, actual_lang = _parse_transcript_file(found_file, video_id, requested_language_code)
        if transcript_text:
            status = 'success'
            logger.debug("[%s] SUCCESS via auto-subs (lang: %s)", video_id, actual_lang)

    # --- Strategy 2: Auto subs without language filter (json3) ---
    if status != 'success':
        logger.debug("[%s] Attempt 2: auto-subs (any language)...", video_id)
        _clean_temp()
        found_file, last_stderr = _run_ytdlp([
            "--write-auto-subs",
            "--sub-langs", ".*",
            "--sub-format", "json3",
        ])
        if found_file:
            transcript_text, actual_lang = _parse_transcript_file(found_file, video_id, requested_language_code)
            if transcript_text:
                status = 'success'
                logger.debug("[%s] SUCCESS via auto-subs any-lang (lang: %s)", video_id, actual_lang)

    # --- Strategy 3: Manual subs with requested language (json3) ---
    if status != 'success':
        logger.debug("[%s] Attempt 3: manual subs (%s)...", video_id, requested_language_code)
        _clean_temp()
        found_file, last_stderr = _run_ytdlp([
            "--write-subs",
            "--sub-langs", f"{requested_language_code}.*",
            "--sub-format", "json3",
        ])
        if found_file:
            transcript_text, actual_lang = _parse_transcript_file(found_file, video_id, requested_language_code)
            if transcript_text:
                status = 'success'
                logger.debug("[%s] SUCCESS via manual subs (lang: %s)", video_id, actual_lang)

    # --- Strategy 4: Manual subs without language filter (json3) ---
    if status != 'success':
        logger.debug("[%s] Attempt 4: manual subs (any language)...", video_id)
        _clean_temp()
        found_file, last_stderr = _run_ytdlp([
            "--write-subs",
            "--sub-langs", ".*",
            "--sub-format", "json3",
        ])
        if found_file:
            transcript_text, actual_lang = _parse_transcript_file(found_file, video_id, requested_language_code)
            if transcript_text:
                status = 'success'
                logger.debug("[%s] SUCCESS via manual subs any-lang (lang: %s)", video_id, actual_lang)

    # --- Strategy 5: Auto subs with vtt / srt fallback format ---
    if status != 'success':
        logger.debug("[%s] Attempt 5: auto-subs (%s) vtt/srt fallback...", video_id, requested_language_code)
        _clean_temp()
        found_file, last_stderr = _run_ytdlp([
            "--write-auto-subs",
            "--sub-langs", f"{requested_language_code}.*",
            "--sub-format", "vtt3/srt",
        ])
        if found_file:
            transcript_text, actual_lang = _parse_transcript_file(found_file, video_id, requested_language_code)
            if transcript_text:
                status = 'success'
                logger.debug("[%s] SUCCESS via auto-subs vtt/srt (lang: %s)", video_id, actual_lang)

    # --- Strategy 6: Auto subs any-lang with vtt / srt fallback format ---
    if status != 'success':
        logger.debug("[%s] Attempt 6: auto-subs (any) vtt/srt fallback...", video_id)
        _clean_temp()
        found_file, last_stderr = _run_ytdlp([
            "--write-auto-subs",
            "--sub-langs", ".*",
            "--sub-format", "vtt3/srt",
        ])
        if found_file:
            transcript_text, actual_lang = _parse_transcript_file(found_file, video_id, requested_language_code)
            if transcript_text:
                status = 'success'
                logger.debug("[%s] SUCCESS via auto-subs any-lang vtt/srt (lang: %s)", video_id, actual_lang)

    # --- Strategy 7: youtube_transcript_api fallback ---
    if status != 'success':
        logger.debug("[%s] Attempt 7: youtube_transcript_api fallback...", video_id)
        try:
            from youtube_transcript_api import YouTubeTranscriptApi
            api = YouTubeTranscriptApi()
            # Phase A: try requested language first
            try:
                transcript = api.fetch(video_id, languages=[requested_language_code])
            except Exception:
                transcript = None
            # Phase B: if requested language failed, try any available language
            if not transcript:
                try:
                    transcript_list = api.list(video_id)
                    available_langs = [t.language_code for t in transcript_list]
                    if available_langs:
                        logger.debug("  Requested lang '%s' not available. Trying: %s...", requested_language_code, available_langs[0])
                        transcript = api.fetch(video_id, languages=[available_langs[0]])
                except Exception:
                    transcript = None
            if transcript:
                transcript_text = " ".join([snippet.text for snippet in transcript])
                transcript_text = re.sub(r' +', ' ', transcript_text).strip()
                if transcript_text:
                    actual_lang = transcript.language_code if hasattr(transcript, 'language_code') else requested_language_code
                    status = 'success'
                    logger.debug("[%s] SUCCESS via youtube_transcript_api (lang: %s)", video_id, actual_lang)
        except Exception as e:
            last_stderr = f"youtube_transcript_api: {e}"

    # --- All attempts failed ---
    if status != 'success':
        last_stderr = last_stderr or "all strategies exhausted"
        if "no suitable subtitles" in last_stderr or "doesn't have subtitles" in last_stderr or "subtitles are not available" in last_stderr:
            status = 'no_transcript'
        else:
            status = 'failed_ytdlp'
        logger.warning("[%s] FAILED (%s): %s...", video_id, status, last_stderr[:120])

    # --- Cleanup temp files ---
    for f_name in list(os.listdir('.')):
        if f_name.startswith(base_name):
            try:
                os.remove(f_name)
            except OSError:
                pass

    # Build a user-friendly error message
    if status == 'success':
        error_detail = None
    elif status == 'no_transcript':
        error_detail = "No transcript or captions are available for this video."
    elif status == 'failed_ytdlp':
        if "timeout" in last_stderr:
            error_detail = "The download timed out. The video may be too long or the server is slow."
        elif "HTTP Error 403" in last_stderr or "HTTP Error 429" in last_stderr:
            error_detail = "YouTube is rate-limiting transcript requests. Please try again later."
        elif "HTTP Error" in last_stderr:
            error_detail = "A network error occurred while fetching the transcript."
        elif last_stderr:
            error_detail = f"Failed to download transcript: {last_stderr[:200]}"
        else:
            error_detail = "Failed to download transcript due to an unknown error."
    else:
        error_detail = last_stderr if last_stderr else "An unknown error occurred."
    
    if error_detail and len(error_detail) > 300:
        error_detail = error_detail[:300] + "..."
    
    return status, transcript_text, actual_lang, error_detail


# --- Core Logic Functions (Search - Unchanged from original, but refined logging/error handling) ---
def search_videos(keyword, max_results=50, language="en", days=None, published_after=None, published_before=None):
    if not youtube:
        logger.warning("YouTube Data API service not initialized. Cannot perform search.")
        return []

    # --- Date Range Logic ---
    search_published_after = None
    search_published_before = None

    if published_after:
        try:
            search_published_after = datetime.strptime(published_after, "%Y-%m-%d").isoformat("T") + "Z"
        except ValueError:
            logger.warning("Invalid published-after date format: %s. Use YYYY-MM-DD. Ignoring.", published_after)
    
    if published_before:
        try:
            search_published_before = datetime.strptime(published_before, "%Y-%m-%d").isoformat("T") + "Z"
        except ValueError:
            logger.warning("Invalid published-before date format: %s. Use YYYY-MM-DD. Ignoring.", published_before)

    if not search_published_after and days:
        now = datetime.now()
        n_days_ago = now - timedelta(days=days)
        search_published_after = n_days_ago.isoformat("T") + "Z"
        if not search_published_before:
            search_published_before = now.isoformat("T") + "Z"


    non_short_video_data = []
    next_page_token = None
    searched_count = 0 # Total videos for which details were requested
    MAX_SEARCH_ITERATIONS = 10
    iteration = 0

    logger.info("Starting video search for keyword: '%s' (lang: %s, max_results: %d)", keyword, language, max_results)
    if search_published_after:
        logger.info("  Published After: %s", search_published_after)
    if search_published_before:
        logger.info("  Published Before: %s", search_published_before)


    while len(non_short_video_data) < max_results and iteration < MAX_SEARCH_ITERATIONS:
        iteration += 1
        logger.info("Fetching search results page %d... (%d non-shorts found so far out of %d)", iteration, len(non_short_video_data), max_results)
        
        results_to_request_this_page = min(50, max(10, (max_results - len(non_short_video_data)) * 2 + 5)) # Heuristic to get enough candidates

        try:
            search_request = youtube.search().list(
                part="snippet", q=keyword, type="video",
                publishedAfter=search_published_after, publishedBefore=search_published_before,
                maxResults=results_to_request_this_page, pageToken=next_page_token, relevanceLanguage=language,
            )
            search_response = search_request.execute()
        except HttpError as e:
            error_content = e.content.decode() if e.content else str(e)
            logger.error("HTTP error %s occurred during search: %s", e.resp.status, error_content)
            if e.resp.status in [400, 403]:
                logger.error("Check API key validity/restrictions/quota for YouTube Data API.")
            break
        except Exception as e:
            logger.exception("Unexpected error occurred during search")
            break

        video_items_on_page = search_response.get("items", [])
        video_ids_on_page = [
            item["id"]["videoId"] for item in video_items_on_page
            if item.get("id", {}).get("kind") == "youtube#video"
        ]

        if not video_ids_on_page:
             logger.debug("No video IDs returned on this search page.")
             next_page_token = search_response.get('nextPageToken')
             if not next_page_token: break
             else: continue

        logger.info("Checking details for %d videos from page %d...", len(video_ids_on_page), iteration)
        try:
            details_request = youtube.videos().list(
                part="contentDetails,id,snippet",
                id=",".join(video_ids_on_page)
            )
            details_response = details_request.execute()
        except HttpError as e:
            error_content = e.content.decode() if e.content else str(e)
            logger.error("HTTP error %s occurred fetching video details: %s", e.resp.status, error_content)
            next_page_token = search_response.get('nextPageToken')
            if not next_page_token: break
            else: continue
        except Exception as e:
            logger.exception("Unexpected error occurred fetching video details")
            next_page_token = search_response.get('nextPageToken')
            if not next_page_token: break
            else: continue

        videos_processed_this_page_details = 0
        for video_details in details_response.get("items", []):
            searched_count +=1
            videos_processed_this_page_details +=1
            duration_str = video_details.get("contentDetails", {}).get("duration")
            duration_seconds = parse_iso8601_duration(duration_str)

            if duration_seconds > 60: # Filter out shorts
                video_id = video_details["id"]
                if not any(d.get('video_id') == video_id for d in non_short_video_data):
                    snippet = video_details.get("snippet", {})
                    thumbs = snippet.get("thumbnails", {})
                    thumb_url = thumbs.get("default", {}).get("url", "") or thumbs.get("medium", {}).get("url", "")
                    video_info = {
                        "video_id": video_id,
                        "title": snippet.get("title", "N/A"),
                        "published_date": snippet.get("publishedAt", "N/A"),
                        "thumbnail_url": thumb_url,
                    }
                    non_short_video_data.append(video_info)
                    logger.debug("+ Added non-short video: %s (Title: %.40s...)", video_id, video_info['title'])
                    if len(non_short_video_data) >= max_results:
                        break 
        
        logger.debug("Processed details for %d videos from this page.", videos_processed_this_page_details)
        if len(non_short_video_data) >= max_results:
            logger.info("Reached target of %d non-short videos.", max_results)
            break

        next_page_token = search_response.get("nextPageToken")
        if not next_page_token:
            logger.info("No more search result pages.")
            break
    
    if iteration >= MAX_SEARCH_ITERATIONS and len(non_short_video_data) < max_results:
        logger.warning("Reached max search iterations (%d). Found %d of %d requested videos.", MAX_SEARCH_ITERATIONS, len(non_short_video_data), max_results)
    elif len(non_short_video_data) < max_results and iteration < MAX_SEARCH_ITERATIONS and next_page_token is None: # Exhausted search before max_results
        logger.warning("Found fewer videos (%d) than requested (%d) after exhausting all search pages.", len(non_short_video_data), max_results)


    logger.info("Finished video search. Total unique non-short videos found: %d. Total videos for which details were checked: %d.", len(non_short_video_data), searched_count)
    return non_short_video_data


# --- Main Execution Logic ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Search YouTube for videos based on a keyword and download their transcripts as a JSONL file.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "-k", "--keyword",
        type=str,
        required=True,
        help="The search term to look for on YouTube."
    )
    parser.add_argument(
        "-l", "--lang",
        type=str,
        default="en",
        help="The two-letter language code for the YouTube search (e.g., 'en', 'es', 'ru')."
    )
    parser.add_argument(
        "-m", "--max-videos",
        type=int,
        default=50,
        help="The maximum number of video transcripts to download."
    )
    parser.add_argument(
        "-d", "--days",
        type=int,
        default=None,
        help="Number of days back to search for videos (default: 60)."
    )
    parser.add_argument(
        "-w", "--weeks",
        type=int,
        default=None,
        help="Number of weeks back to search for videos."
    )
    parser.add_argument(
        "--published-after",
        type=str,
        help="Search for videos published after this date (YYYY-MM-DD)."
    )
    parser.add_argument(
        "--published-before",
        type=str,
        help="Search for videos published before this date (YYYY-MM-DD)."
    )

    args = parser.parse_args()

    search_keyword = args.keyword
    search_language = args.lang
    max_videos_to_process = args.max_videos


    logger.info("--- YouTube Transcript Downloader to JSONL Script (using yt-dlp) ---")
    
    # Cleanup any leftovers from previous runs
    cleanup_temp_files()

    if not youtube and max_videos_to_process > 0:
        logger.warning("YouTube Data API service for search is not initialized.")
        logger.warning("Script will not be able to search for new videos.")

    logger.info("Preparing output file for keyword: '%s'", search_keyword)
    try:
        os.makedirs(BASE_OUTPUT_FOLDER, exist_ok=True)
        logger.info("Base output folder: %s", BASE_OUTPUT_FOLDER)
    except OSError as e:
        logger.error("Error creating base directory %s: %s", BASE_OUTPUT_FOLDER, e)
        logger.error("Exiting script.")
        exit()

    file_name = clean_filename(search_keyword) + ".jsonl"
    output_filepath = os.path.join(BASE_OUTPUT_FOLDER, file_name)
    logger.info("Output file: %s", output_filepath)

    # Determine lookback days (priority: days > weeks > default 60)
    lookback_days = 60
    if args.days is not None:
        lookback_days = args.days
    elif args.weeks is not None:
        lookback_days = args.weeks * 7

    video_data_list = search_videos(
        keyword=search_keyword,
        max_results=max_videos_to_process,
        language=search_language,
        days=lookback_days,
        published_after=args.published_after,
        published_before=args.published_before
    )

    logger.info("Found %d non-Short videos matching search criteria.", len(video_data_list))

    success_count = 0
    failure_count = 0
    skipped_existing = 0
    empty_transcript_count = 0

    processed_ids = set()
    if os.path.exists(output_filepath):
        logger.info("Checking existing file for processed IDs: %s", output_filepath)
        try:
            with open(output_filepath, 'r', encoding='utf-8') as f_check:
                for line in f_check:
                    try:
                        data = json.loads(line)
                        if 'video_id' in data:
                            processed_ids.add(data['video_id'])
                    except json.JSONDecodeError:
                        logger.warning("Skipping malformed line in existing file: %s", line.strip())
            logger.info("Found %d IDs already in the file.", len(processed_ids))
        except Exception as e:
            logger.warning("Could not read existing file to check IDs: %s", e)

    if video_data_list:
        logger.info("Starting transcript processing and saving to JSONL using yt-dlp...")
        try:
            with open(output_filepath, 'a', encoding='utf-8') as outfile:
                for i, video_info in enumerate(video_data_list, 1):
                    vid_id = video_info['video_id']
                    logger.info("Processing video %d/%d: %s (Title: %.50s...)", i, len(video_data_list), vid_id, video_info.get('title', 'N/A'))

                    if vid_id in processed_ids:
                        logger.info("- Video ID %s already processed/exists in file. Skipping.", vid_id)
                        skipped_existing += 1
                        continue

                    status, transcript_text, actual_lang, error_detail = download_transcript_ytdlp(vid_id, search_language)

                    if status == 'success':
                        if transcript_text: 
                            full_data = {
                                "video_id": vid_id,
                                "search_keyword": search_keyword,
                                "search_language": search_language,
                                "title": video_info.get("title", "N/A"),
                                "published_date": video_info.get("published_date", "N/A"),
                                "transcript_language": actual_lang if actual_lang else search_language,
                                "transcript": transcript_text
                            }
                            json.dump(full_data, outfile, ensure_ascii=False)
                            outfile.write('\n')
                            outfile.write('\n')
                            success_count += 1
                        else: 
                            logger.info("- Video ID %s had an empty transcript (fetched successfully).", vid_id)
                            empty_transcript_count +=1
                    else:
                        reason = error_detail or "unknown error"
                        logger.warning("- Failed to get transcript for %s. Status: %s. Detail: %.200s", vid_id, status, reason)
                        failure_count += 1
                    
                    processed_ids.add(vid_id)

                    if ADD_DELAY_BETWEEN_TRANSCRIPTS > 0 and i < len(video_data_list):
                        logger.debug("Waiting %ds...", ADD_DELAY_BETWEEN_TRANSCRIPTS)
                        time.sleep(ADD_DELAY_BETWEEN_TRANSCRIPTS)

        except IOError as e:
            logger.error("CRITICAL ERROR: Could not write to output file %s: %s", output_filepath, e)
            logger.error("Data for this session may be lost or incomplete.")
            failure_count = len(video_data_list) - success_count - skipped_existing - empty_transcript_count

    logger.info("--- Transcript Processing Summary (yt-dlp) ---")
    logger.info("Keyword: '%s'", search_keyword)
    logger.info("Language Searched: %s", search_language)
    logger.info("Videos Found (Non-Short, Searched): %d", len(video_data_list))
    logger.info("Successful Downloads & Saves (with text): %d", success_count)
    logger.info("Successfully Fetched Empty Transcripts: %d", empty_transcript_count)
    logger.info("Skipped (Already in File): %d", skipped_existing)
    logger.info("Failures (No transcript/yt-dlp error): %d", failure_count)
    logger.info("Data saved in: %s", output_filepath)
    logger.info("---------------------------------------------")

    # Generate CSV
    generate_csv(output_filepath, video_data_list)

    # Final cleanup
    cleanup_temp_files()

    logger.info("Script finished.")