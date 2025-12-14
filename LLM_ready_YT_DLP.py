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


load_dotenv('.env.local')
api_key = os.getenv("YOUTUBE_API_KEY")

# --- Configuration ---
BASE_OUTPUT_FOLDER = "llm_data"
ADD_DELAY_BETWEEN_TRANSCRIPTS = 1 # Seconds (0 to disable)

# --- YouTube Data API Service Initialization (for video search) ---
youtube = None
try:
    if not api_key:
        print("Error: YOUTUBE_API_KEY is missing from .env.local.")
        print("Please add it to your .env.local file if you need video search.")
    else:
        youtube = build("youtube", "v3", developerKey=api_key)
        print("YouTube Data API service initialized successfully (for video search).")
except Exception as e:
    print(f"Error building YouTube Data API service: {e}")

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
                print(f" Warning: Could not remove temp file {f_name}: {e}")
    if count > 0:
        print(f"Cleaned up {count} temporary transcript files.")

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
        print(f"\nReading historical IDs from {jsonl_path}...")
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
            print(f"Error reading JSONL file: {e}")

    # 2. Add IDs from the current search (all found)
    if current_video_list:
        print(f"Adding {len(current_video_list)} IDs from current search...")
        for video_info in current_video_list:
            all_video_ids.add(video_info['video_id'])

    if not all_video_ids:
        print("No URLs found to export to CSV.")
        return

    # Convert to URLs
    urls = [[f"https://www.youtube.com/watch?v={vid}"] for vid in all_video_ids]

    print(f"Generating CSV with {len(urls)} total URLs...")

    try:
        with open(csv_output_path, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(['Video URL']) # Header
            writer.writerows(urls)
        print(f"Successfully wrote {len(urls)} URLs to {csv_output_path}")
    except Exception as e:
        print(f"Error writing to CSV: {e}")

# --- yt-dlp Transcript Fetch Function (with improved formatting) ---
def download_transcript_ytdlp(video_id, requested_language_code="en"):
    """
    Downloads transcript for a video ID using yt-dlp.
    Attempts to format the transcript by joining segments within an event with spaces,
    and events with newlines.

    Args:
        video_id (str): The YouTube video ID.
        requested_language_code (str): The desired language code (e.g., "en", "es").

    Returns:
        tuple: (status, transcript_text, actual_language_code)
               status: 'success', 'no_transcript', 'failed_ytdlp', 'error_ytdlp'
               transcript_text: The transcript, or None
               actual_language_code: The language code used, or None
    """
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    base_name = f"temp_transcript_{video_id}" # For temporary files

    command = [
        "yt-dlp",
        video_url,
        "--write-auto-subs",
        "--sub-langs", f"{requested_language_code}.*", # Match language and variants
        "--sub-format", "json3",
        "--skip-download",
        "-o", base_name,
        "--no-warnings",
        "--proxy", "",
    ]

    transcript_text = None
    actual_lang = None
    status = 'error_ytdlp' # Default to a generic error

    print(f"  Attempting transcript download for {video_id} with yt-dlp (lang: {requested_language_code})...")
    try:
        process = subprocess.run(command, check=False, capture_output=True, text=True, encoding='utf-8', timeout=60)

        if process.returncode != 0:
            print(f"  yt-dlp for {video_id} exited with code {process.returncode}.")
            print(f"  yt-dlp STDERR: {process.stderr.strip()[:500]}...")
            if "no suitable subtitles found" in process.stderr.lower() or \
               "requested subtitle formats are not available" in process.stderr.lower() or \
               "video doesn't have subtitles" in process.stderr.lower() or \
               "Video unavailable" in process.stderr:
                status = 'no_transcript'
            else:
                status = 'failed_ytdlp'
            return status, None, None

        downloaded_file_path = None
        for f_name in os.listdir('.'):
            if f_name.startswith(base_name) and f_name.endswith('.json3'):
                downloaded_file_path = f_name
                try:
                    actual_lang = f_name.split('.')[-2]
                except IndexError:
                    actual_lang = requested_language_code
                print(f"  Found transcript file: {downloaded_file_path} (actual lang: {actual_lang})")
                break
        
        if not downloaded_file_path:
            print(f"  ERROR: yt-dlp ran (exit 0), but no .json3 transcript file found for {video_id}.")
            return 'no_transcript', None, None

        with open(downloaded_file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # --- MODIFIED TRANSCRIPT PARSING FOR BETTER FORMATTING ---
        event_texts = []
        if "events" in data:
            for event in data["events"]:
                segment_texts_for_event = []
                if "segs" in event:
                    for seg in event["segs"]:
                        if "utf8" in seg:
                            # Append segment text, stripping individual segment whitespace
                            segment_texts_for_event.append(seg["utf8"].strip()) 
                if segment_texts_for_event:
                    # Join segments within an event with a single space
                    event_texts.append(" ".join(segment_texts_for_event))
        
        # Join different events (which were separate caption displays) with a newline
        transcript_text_raw = "\n".join(event_texts)
        
        # Further cleanup:
        # Replace multiple spaces with a single space
        transcript_text = re.sub(r' +', ' ', transcript_text_raw).strip()
        # Optional: Convert sequences of newline+space(s)+newline to double newline (paragraph break)
        # transcript_text = re.sub(r'\n\s*\n', '\n\n', transcript_text) 
        # --- END OF MODIFIED PARSING ---

        if transcript_text:
            status = 'success'
            print(f"  SUCCESS: Transcript fetched via yt-dlp for {video_id} (lang: {actual_lang}).")
        else:
            status = 'success' # Success, but transcript was empty after processing
            print(f"  SUCCESS (empty): yt-dlp fetched an empty transcript for {video_id} (lang: {actual_lang}).")
            transcript_text = "" # Ensure it's an empty string

    except FileNotFoundError:
        print("  CRITICAL ERROR: yt-dlp command not found. Is it installed and in PATH?")
        status = 'error_ytdlp'
    except subprocess.TimeoutExpired:
        print(f"  ERROR: yt-dlp command timed out for {video_id}.")
        status = 'failed_ytdlp'
    except json.JSONDecodeError as e:
        print(f"  ERROR: Failed to parse JSON from transcript file for {video_id}: {e}")
        status = 'error_ytdlp'
    except Exception as e:
        print(f"  ERROR: An unexpected error occurred processing transcript for {video_id} with yt-dlp: {e}")
        traceback.print_exc()
        status = 'error_ytdlp'
    finally:
        for f_name in os.listdir('.'):
            if f_name.startswith(base_name) and f_name.endswith('.json3'):
                try:
                    os.remove(f_name)
                except OSError as e_os:
                    print(f"  Warning: Could not remove temp file {f_name}: {e_os}")
    
    return status, transcript_text, actual_lang


# --- Core Logic Functions (Search - Unchanged from original, but refined logging/error handling) ---
def search_videos(keyword, max_results=50, language="en", days=None, published_after=None, published_before=None):
    if not youtube:
        print("YouTube Data API service not initialized. Cannot perform search.")
        return []

    # --- Date Range Logic ---
    search_published_after = None
    search_published_before = None

    if published_after:
        try:
            search_published_after = datetime.strptime(published_after, "%Y-%m-%d").isoformat("T") + "Z"
        except ValueError:
            print(f"Warning: Invalid published-after date format: {published_after}. Use YYYY-MM-DD. Ignoring.")
    
    if published_before:
        try:
            search_published_before = datetime.strptime(published_before, "%Y-%m-%d").isoformat("T") + "Z"
        except ValueError:
            print(f"Warning: Invalid published-before date format: {published_before}. Use YYYY-MM-DD. Ignoring.")

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

    print(f"\nStarting video search for keyword: '{keyword}' (lang: {language}, max_results: {max_results})")
    if search_published_after:
        print(f"  Published After: {search_published_after}")
    if search_published_before:
        print(f"  Published Before: {search_published_before}")


    while len(non_short_video_data) < max_results and iteration < MAX_SEARCH_ITERATIONS:
        iteration += 1
        print(f" Fetching search results page {iteration}... ({len(non_short_video_data)} non-shorts found so far out of {max_results})")
        
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
            print(f" An HTTP error {e.resp.status} occurred during search:\n {error_content}")
            if e.resp.status in [400, 403]: print(" Check API key validity/restrictions/quota for YouTube Data API.")
            break
        except Exception as e:
            print(f" An unexpected error occurred during search: {e}")
            traceback.print_exc()
            break

        video_items_on_page = search_response.get("items", [])
        video_ids_on_page = [
            item["id"]["videoId"] for item in video_items_on_page
            if item.get("id", {}).get("kind") == "youtube#video"
        ]

        if not video_ids_on_page:
             print("  No video IDs returned on this search page.")
             next_page_token = search_response.get('nextPageToken')
             if not next_page_token: break
             else: continue

        print(f"  Checking details for {len(video_ids_on_page)} videos from page {iteration}...")
        try:
            details_request = youtube.videos().list(
                part="contentDetails,id,snippet",
                id=",".join(video_ids_on_page)
            )
            details_response = details_request.execute()
        except HttpError as e:
            error_content = e.content.decode() if e.content else str(e)
            print(f"  An HTTP error {e.resp.status} occurred fetching video details:\n {error_content}")
            next_page_token = search_response.get('nextPageToken')
            if not next_page_token: break
            else: continue
        except Exception as e:
             print(f"  An unexpected error occurred fetching video details: {e}")
             traceback.print_exc()
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
                    video_info = {
                        "video_id": video_id,
                        "title": snippet.get("title", "N/A"),
                        "published_date": snippet.get("publishedAt", "N/A")
                    }
                    non_short_video_data.append(video_info)
                    print(f"   + Added non-short video: {video_id} (Title: {video_info['title'][:40]}...)")
                    if len(non_short_video_data) >= max_results:
                        break 
        
        print(f"  Processed details for {videos_processed_this_page_details} videos from this page.")
        if len(non_short_video_data) >= max_results:
            print(f" Reached target of {max_results} non-short videos.")
            break

        next_page_token = search_response.get("nextPageToken")
        if not next_page_token:
            print(" No more search result pages.")
            break
    
    if iteration >= MAX_SEARCH_ITERATIONS and len(non_short_video_data) < max_results:
        print(f"\nWarning: Reached max search iterations ({MAX_SEARCH_ITERATIONS}). Found {len(non_short_video_data)} of {max_results} requested videos.")
    elif len(non_short_video_data) < max_results and iteration < MAX_SEARCH_ITERATIONS and next_page_token is None : # Exhausted search before max_results
         print(f"\nWarning: Found fewer videos ({len(non_short_video_data)}) than requested ({max_results}) after exhausting all search pages.")


    print(f"\nFinished video search. Total unique non-short videos found: {len(non_short_video_data)}. Total videos for which details were checked: {searched_count}.")
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


    print("--- YouTube Transcript Downloader to JSONL Script (using yt-dlp) ---")
    
    # Cleanup any leftovers from previous runs
    cleanup_temp_files()

    if not youtube and max_videos_to_process > 0:
        print("\nWarning: YouTube Data API service for search is not initialized.")
        print("Script will not be able to search for new videos.")

    print(f"\nPreparing output file for keyword: '{search_keyword}'")
    try:
        os.makedirs(BASE_OUTPUT_FOLDER, exist_ok=True)
        print(f" Base output folder: {BASE_OUTPUT_FOLDER}")
    except OSError as e:
        print(f" Error creating base directory {BASE_OUTPUT_FOLDER}: {e}")
        print("Exiting script.")
        exit()

    file_name = clean_filename(search_keyword) + ".jsonl"
    output_filepath = os.path.join(BASE_OUTPUT_FOLDER, file_name)
    print(f" Output file: {output_filepath}")

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

    print(f"\nFound {len(video_data_list)} non-Short videos matching search criteria.")

    success_count = 0
    failure_count = 0
    skipped_existing = 0
    empty_transcript_count = 0

    processed_ids = set()
    if os.path.exists(output_filepath):
        print(f"\nChecking existing file for processed IDs: {output_filepath}")
        try:
            with open(output_filepath, 'r', encoding='utf-8') as f_check:
                for line in f_check:
                    try:
                        data = json.loads(line)
                        if 'video_id' in data:
                            processed_ids.add(data['video_id'])
                    except json.JSONDecodeError:
                        print(f" Warning: Skipping malformed line in existing file: {line.strip()}")
            print(f" Found {len(processed_ids)} IDs already in the file.")
        except Exception as e:
            print(f" Warning: Could not read existing file to check IDs: {e}")

    if video_data_list:
        print("\nStarting transcript processing and saving to JSONL using yt-dlp...")
        try:
            with open(output_filepath, 'a', encoding='utf-8') as outfile:
                for i, video_info in enumerate(video_data_list, 1):
                    vid_id = video_info['video_id']
                    print(f" Processing video {i}/{len(video_data_list)}: {vid_id} (Title: {video_info.get('title', 'N/A')[:50]}...)")

                    if vid_id in processed_ids:
                        print(f"  - Video ID {vid_id} already processed/exists in file. Skipping.")
                        skipped_existing += 1
                        continue

                    status, transcript_text, actual_lang = download_transcript_ytdlp(vid_id, search_language)

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
                            #json.dump(full_data, outfile)
                            json.dump(full_data, outfile, ensure_ascii=False)
                            outfile.write('\n')
                            outfile.write('\n')
                            success_count += 1
                        else: 
                            print(f"  - Video ID {vid_id} had an empty transcript (fetched successfully).")
                            empty_transcript_count +=1
                    else:
                        print(f"  - Failed to get transcript for {vid_id}. Status from yt-dlp: {status}")
                        failure_count += 1
                    
                    processed_ids.add(vid_id)

                    if ADD_DELAY_BETWEEN_TRANSCRIPTS > 0 and i < len(video_data_list):
                        print(f"   Waiting {ADD_DELAY_BETWEEN_TRANSCRIPTS}s...")
                        time.sleep(ADD_DELAY_BETWEEN_TRANSCRIPTS)

        except IOError as e:
            print(f"\nCRITICAL ERROR: Could not write to output file {output_filepath}: {e}")
            print("Data for this session may be lost or incomplete.")
            failure_count = len(video_data_list) - success_count - skipped_existing - empty_transcript_count

    print("\n--- Transcript Processing Summary (yt-dlp) ---")
    print(f" Keyword: '{search_keyword}'")
    print(f" Language Searched: {search_language}")
    print(f" Videos Found (Non-Short, Searched): {len(video_data_list)}")
    print(f" Successful Downloads & Saves (with text): {success_count}")
    print(f" Successfully Fetched Empty Transcripts: {empty_transcript_count}")
    print(f" Skipped (Already in File): {skipped_existing}")
    print(f" Failures (No transcript/yt-dlp error): {failure_count}")
    print(f" Data saved in: {output_filepath}")
    print("---------------------------------------------")

    # Generate CSV
    generate_csv(output_filepath, video_data_list)

    # Final cleanup
    cleanup_temp_files()

    print("\nScript finished.")