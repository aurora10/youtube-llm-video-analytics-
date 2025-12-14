import re
import os
import json # Added for JSON operations
import time # Added for potential delays
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from datetime import datetime, timedelta
from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound, TranscriptsDisabled
import traceback # Optional: for more detailed error logging
from dotenv import load_dotenv

# --- IMPORTANT SECURITY WARNING ---
# As requested, security is bypassed for now. In a real application,
# NEVER hardcode API keys. Use environment variables or secret managers.
load_dotenv('.env.local')
api_key = os.getenv("YOUTUBE_API_KEY")

# --- Configuration ---
BASE_OUTPUT_FOLDER = "llm_data" # Base folder for JSONL files
ADD_DELAY_BETWEEN_TRANSCRIPTS = 1 # Seconds to wait between transcript downloads (0 to disable)

# --- YouTube Data API Service Initialization ---
youtube = None # Initialize as None
try:
    if not api_key:
        print("Error: YOUTUBE_API_KEY is missing from .env.local.")
        print("Please add it to your .env.local file.")
    else:
        youtube = build("youtube", "v3", developerKey=api_key)
        print("YouTube service initialized successfully.")
except Exception as e:
    print(f"Error building YouTube service: {e}")


# --- Helper Functions ---

def parse_iso8601_duration(duration_str):
    """Parses an ISO 8601 duration string into seconds."""
    if not duration_str: return 0
    match = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?', duration_str)
    if not match: return 0
    hours = int(match.group(1)) if match.group(1) else 0
    minutes = int(match.group(2)) if match.group(2) else 0
    seconds = float(match.group(3)) if match.group(3) else 0
    return int(hours * 3600 + minutes * 60 + seconds)

def clean_filename(name):
    """Removes or replaces invalid characters for filenames."""
    name = re.sub(r'[\\/*?:"<>|]+', '', name)
    name = re.sub(r'[^\w\-]+', '_', name)
    name = name.strip('_-')
    name = name[:100]
    return name if name else "invalid_keyword"

# --- Core Logic Functions ---

def search_videos_last_month(keyword, max_results=50, language="en"):
    """Searches YouTube for non-Short videos published in the last 60 days
    matching the keyword and language relevance.
    Returns a list of dictionaries containing video metadata (id, title, publishedAt)."""

    if not youtube:
        print("YouTube service not initialized. Cannot perform search.")
        return []

    now = datetime.now()
    sixty_days_ago = now - timedelta(days=60)
    published_after = sixty_days_ago.isoformat("T") + "Z"
    published_before = now.isoformat("T") + "Z"

    # Store dicts of video data for non-shorts
    non_short_video_data = []
    next_page_token = None
    searched_count = 0
    MAX_SEARCH_ITERATIONS = 10
    iteration = 0

    print(f"\nStarting video search for keyword: '{keyword}' (lang: {language}, max_results: {max_results})")

    while len(non_short_video_data) < max_results and iteration < MAX_SEARCH_ITERATIONS:
        iteration += 1
        print(f" Fetching search results page {iteration}... ({len(non_short_video_data)} non-shorts found so far)")
        results_to_request = min(50, (max_results - len(non_short_video_data)) * 2 + 5)

        try:
            search_request = youtube.search().list(
                part="snippet", q=keyword, type="video",
                publishedAfter=published_after, publishedBefore=published_before,
                maxResults=results_to_request, pageToken=next_page_token, relevanceLanguage=language,
            )
            search_response = search_request.execute()
        except HttpError as e:
            error_content = e.content.decode() if e.content else str(e)
            print(f" An HTTP error {e.resp.status} occurred during search:\n {error_content}")
            if e.resp.status in [400, 403]: print(" Check API key validity/restrictions/quota.")
            break
        except Exception as e:
            print(f" An unexpected error occurred during search: {e}")
            traceback.print_exc()
            break

        video_ids_on_page = [
            item["id"]["videoId"] for item in search_response.get("items", [])
            if item.get("id", {}).get("kind") == "youtube#video"
        ]

        if not video_ids_on_page:
             print("  No video IDs returned on this search page.")
             next_page_token = search_response.get('nextPageToken')
             if not next_page_token: break
             else: continue

        # --- Get video details (duration, snippet) ---
        print(f"  Checking details for {len(video_ids_on_page)} videos from page {iteration}...")
        try:
            # Fetch contentDetails (duration) AND snippet (title, publishedAt)
            details_request = youtube.videos().list(
                part="contentDetails,id,snippet", # Added snippet
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

        # Process details and filter by duration
        videos_processed_on_page = 0
        for video_details in details_response.get("items", []):
            searched_count += 1
            videos_processed_on_page += 1
            duration_str = video_details.get("contentDetails", {}).get("duration")
            duration_seconds = parse_iso8601_duration(duration_str)

            if duration_seconds > 60: # Filter out shorts
                video_id = video_details["id"]
                # Check if we already added this ID (unlikely but possible)
                if not any(d.get('video_id') == video_id for d in non_short_video_data):
                    # Extract relevant info into a dictionary
                    snippet = video_details.get("snippet", {})
                    video_info = {
                        "video_id": video_id,
                        "title": snippet.get("title", "N/A"),
                        "published_date": snippet.get("publishedAt", "N/A")
                        # Note: 'transcript', 'transcript_language' etc. will be added later
                    }
                    non_short_video_data.append(video_info)
                    print(f"   + Added non-short video: {video_id} (Title: {video_info['title'][:30]}...)")

                    if len(non_short_video_data) >= max_results:
                        break # Stop processing details loop if target reached

        print(f"  Processed details for {videos_processed_on_page} videos.")
        if len(non_short_video_data) >= max_results:
            print(f" Reached target of {max_results} non-short videos.")
            break # Stop searching pages

        next_page_token = search_response.get("nextPageToken")
        if not next_page_token:
            print(" No more search result pages.")
            break

    # --- End of while loop ---
    if iteration >= MAX_SEARCH_ITERATIONS and len(non_short_video_data) < max_results:
         print(f"\nWarning: Reached max search iterations ({MAX_SEARCH_ITERATIONS}). Found {len(non_short_video_data)} videos.")
    elif len(non_short_video_data) < max_results:
         print(f"\nWarning: Found fewer videos ({len(non_short_video_data)}) than requested ({max_results}).")

    print(f"\nFinished video search. Total videos checked: {searched_count}.")
    # Return the list of dictionaries containing metadata
    return non_short_video_data


def download_transcript(video_id, requested_language_code):
    """Downloads transcript for a video ID using fallback logic.
    Returns tuple: (status, transcript_text, actual_language_code)
    status is 'success', 'no_transcript_found', 'disabled', 'failed'
    """
    print(f"  Attempting transcript download for {video_id} (req lang: {requested_language_code})...")
    transcript_text = None
    actual_language_code = None
    status = 'failed' # Default status

    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        transcript = None

        # --- Language Fallback Logic ---
        language_options = [requested_language_code, 'en'] # Prioritize requested, then English
        found = False
        for lang in language_options:
            if found: break
            try:
                # Try manual first
                transcript = transcript_list.find_transcript([lang])
                actual_language_code = transcript.language_code # Use precise code
                print(f"   Found manual transcript in '{actual_language_code}'.")
                found = True
            except NoTranscriptFound:
                print(f"   No manual transcript in '{lang}'. Checking generated...")
                try:
                    # Try generated
                    transcript = transcript_list.find_generated_transcript([lang])
                    actual_language_code = transcript.language_code # Use precise code
                    print(f"   Found generated transcript in '{actual_language_code}'.")
                    found = True
                except NoTranscriptFound:
                    print(f"   No generated transcript in '{lang}'.")
                    # Only print trying next language if there IS a next language
                    if lang != language_options[-1]:
                         print(f"   Trying next fallback language...")
                    continue # Try next language in language_options

        # --- Process if found ---
        if transcript and found:
            transcript_data = transcript.fetch()

            # --- !!! THE CORRECTED LINE IS HERE !!! ---
            # Use attribute access (.text) instead of dictionary access (['text'])
            transcript_text = "\n".join([item.text for item in transcript_data])
            # --- End of Fix ---

            status = 'success'
            print(f"  SUCCESS: Transcript fetched for {video_id} (lang: {actual_language_code})")
        elif not found:
            # If loop finishes without finding anything
            print(f"   ERROR: No suitable transcript found for {video_id} after checking {language_options}.")
            status = 'no_transcript_found'

    except TranscriptsDisabled:
        print(f"  ERROR: Transcripts are disabled for video {video_id}.")
        status = 'disabled'
    except Exception as e:
        print(f"  ERROR: Could not process transcript for {video_id}: {e}")
        # traceback.print_exc() # Uncomment for detailed debugging
        status = 'failed' # Keep status as failed

    return status, transcript_text, actual_language_code

# --- Main Execution Logic ---
if __name__ == "__main__":

    # --- User Configuration ---
    search_keyword = "how to get E-2 visa" # <--- CHANGE KEYWORD HERE
    search_language = "en"                 # <--- CHANGE LANGUAGE HERE (e.g., "ru", "es", "en")
    max_videos_to_process = 400         # <--- CHANGE NUMBER OF VIDEOS HERE

    print("--- YouTube Transcript Downloader to JSONL Script ---")

    # --- Check YouTube Service ---
    if not youtube:
        print("\nCritical Error: YouTube service could not be initialized.")
        print("Exiting script.")
        exit()

    # --- Prepare Output File ---
    print(f"\nPreparing output file for keyword: '{search_keyword}'")
    # Create base output folder if it doesn't exist
    try:
        os.makedirs(BASE_OUTPUT_FOLDER, exist_ok=True)
        print(f" Base output folder: {BASE_OUTPUT_FOLDER}")
    except OSError as e:
        print(f" Error creating base directory {BASE_OUTPUT_FOLDER}: {e}")
        print("Exiting script.")
        exit()

    # Create filename for this keyword's JSONL
    file_name = clean_filename(search_keyword) + ".jsonl"
    output_filepath = os.path.join(BASE_OUTPUT_FOLDER, file_name)
    print(f" Output file: {output_filepath}")

    # --- Search for Videos ---
    # Get list of dictionaries containing video metadata
    video_data_list = search_videos_last_month(
        search_keyword,
        max_results=max_videos_to_process,
        language=search_language
    )

    print(f"\nFound {len(video_data_list)} non-Short videos matching criteria.")

    # --- Download Transcripts and Save to JSONL ---
    success_count = 0
    failure_count = 0 # Includes disabled, not found, errors
    skipped_existing = 0 # Count how many were skipped because they were already in the file

    # Keep track of IDs already processed in this run or existing in the file
    processed_ids = set()

    # Check existing file for IDs (optional but good for resuming)
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
        print("\nStarting transcript processing and saving to JSONL...")
        # Open file in append mode
        try:
            with open(output_filepath, 'a', encoding='utf-8') as outfile:
                for i, video_info in enumerate(video_data_list, 1):
                    vid_id = video_info['video_id']
                    print(f" Processing video {i}/{len(video_data_list)}: {vid_id}")

                    # Skip if already processed in this run or exists in file
                    if vid_id in processed_ids:
                        print(f"  - Video ID {vid_id} already processed/exists in file. Skipping.")
                        skipped_existing += 1
                        continue

                    # Download transcript (returns status, text, actual_lang)
                    status, transcript_text, actual_lang = download_transcript(vid_id, search_language)

                    # Prepare full data object if successful
                    if status == 'success' and transcript_text is not None:
                        full_data = {
                            "video_id": vid_id,
                            "search_keyword": search_keyword,
                            "search_language": search_language,
                            "title": video_info.get("title", "N/A"),
                            "published_date": video_info.get("published_date", "N/A"),
                            "transcript_language": actual_lang, # The language actually found
                            "transcript": transcript_text
                        }
                        # Write the JSON object as a line in the file
                        json.dump(full_data, outfile, ensure_ascii=False)
                        outfile.write('\n') # Add newline for JSONL format
                        success_count += 1
                        processed_ids.add(vid_id) # Mark as processed for this run
                    else:
                        # Count all non-success cases as failures for summary
                        failure_count += 1
                        processed_ids.add(vid_id) # Also mark failures as processed to avoid retrying in this run

                    # Optional Delay
                    if ADD_DELAY_BETWEEN_TRANSCRIPTS > 0:
                        print(f"   Waiting {ADD_DELAY_BETWEEN_TRANSCRIPTS}s...")
                        time.sleep(ADD_DELAY_BETWEEN_TRANSCRIPTS)

        except IOError as e:
             print(f"\nCRITICAL ERROR: Could not write to output file {output_filepath}: {e}")
             print("Data for this session may be lost.")
             # Update failure count based on remaining videos?
             failure_count = len(video_data_list) - success_count - skipped_existing

    # --- Final Summary ---
    print("\n--- Transcript Processing Summary ---")
    print(f" Keyword: '{search_keyword}'")
    print(f" Language: {search_language}")
    print(f" Videos Found (Non-Short): {len(video_data_list)}")
    print(f" Successful Downloads & Saves: {success_count}")
    print(f" Skipped (Already in File): {skipped_existing}")
    print(f" Failures (No transcript/Disabled/Error): {failure_count}")
    print(f" Data saved in: {output_filepath}")
    print("--------------------------------------")

    print("\nScript finished.")