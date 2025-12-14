import json
import csv
import os

# Configuration
INPUT_FILE = "llm_data/deportation_of_ukranians_from_us.jsonl"
OUTPUT_FILE = "video_urls.csv"

def main():
    if not os.path.exists(INPUT_FILE):
        print(f"Error: Input file '{INPUT_FILE}' not found.")
        return

    urls = []
    print(f"Reading from {INPUT_FILE}...")
    
    try:
        with open(INPUT_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    if 'video_id' in data:
                        video_url = f"https://www.youtube.com/watch?v={data['video_id']}"
                        urls.append([video_url])
                except json.JSONDecodeError:
                    print(f"Warning: Skipping malformed line: {line[:50]}...")
    except Exception as e:
        print(f"Error reading file: {e}")
        return

    if not urls:
        print("No URLs found to export.")
        return

    print(f"Found {len(urls)} URLs. Writing to {OUTPUT_FILE}...")
    
    try:
        with open(OUTPUT_FILE, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(['Video URL']) # Header
            writer.writerows(urls)
        print(f"Successfully wrote {len(urls)} URLs to {OUTPUT_FILE}")
    except Exception as e:
        print(f"Error writing to CSV: {e}")

if __name__ == "__main__":
    main()
