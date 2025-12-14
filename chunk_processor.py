import json
import re
import os

# --- Configuration ---
# The output folder
OUTPUT_FOLDER = "OUTPUT"

# --- Chunking Parameters ---
# NOTE: This is based on words. A more accurate method uses tokenizers (like tiktoken for OpenAI models),
# but word count is a good and simple proxy.
MAX_WORDS_PER_CHUNK = 400  # The target size for each chunk. Adjust based on your LLM's context window.
OVERLAP_WORDS = 50       # How many words to overlap between consecutive chunks.

def chunk_text(text: str, max_words: int, overlap_words: int) -> list[str]:
    """
    Splits a long text into smaller, overlapping chunks that respect paragraph boundaries.
    """
    # 1. Split the text into paragraphs
    paragraphs = re.split(r'\n\s*\n', text)
    
    all_chunks = []
    current_chunk_words = []

    for paragraph in paragraphs:
        if not paragraph.strip():
            continue
        
        words = paragraph.split()
        
        # If a single paragraph is larger than the max size, we must split it forcefully.
        if len(words) > max_words:
            # Force-split the oversized paragraph
            start = 0
            while start < len(words):
                end = start + max_words
                chunk = words[start:end]
                all_chunks.append(" ".join(chunk))
                start += max_words - overlap_words # Move window forward with overlap
            continue # Move to the next paragraph

        # If adding this paragraph fits within the current chunk, add it
        if len(current_chunk_words) + len(words) <= max_words:
            current_chunk_words.extend(words)
        else:
            # 2. The current chunk is full. Finalize and append it.
            all_chunks.append(" ".join(current_chunk_words))
            
            # 3. Start a new chunk, including overlap from the previous one.
            overlap_start_index = max(0, len(current_chunk_words) - overlap_words)
            new_chunk_with_overlap = current_chunk_words[overlap_start_index:]
            
            # Add the current paragraph to the new chunk
            current_chunk_words = new_chunk_with_overlap + words

    # 4. Add the last remaining chunk
    if current_chunk_words:
        all_chunks.append(" ".join(current_chunk_words))
        
    return all_chunks


# --- Main Processing Logic ---
if __name__ == "__main__":
    print("--- Chunk Processor ---")
    input_file_path = input("Enter the path to the input JSONL file: ").strip()
    
    # Remove quotes if the user dragged and dropped the file
    if input_file_path.startswith('"') and input_file_path.endswith('"'):
        input_file_path = input_file_path[1:-1]
    elif input_file_path.startswith("'") and input_file_path.endswith("'"):
        input_file_path = input_file_path[1:-1]

    if not os.path.exists(input_file_path):
        print(f"Error: Input file not found at '{input_file_path}'")
        exit()

    # Create OUTPUT folder if it doesn't exist
    if not os.path.exists(OUTPUT_FOLDER):
        os.makedirs(OUTPUT_FOLDER)
        print(f"Created output directory: {OUTPUT_FOLDER}")

    # Construct output filename
    base_name = os.path.basename(input_file_path)
    output_filename = f"{base_name}_chunked.jsonl"
    output_file_path = os.path.join(OUTPUT_FOLDER, output_filename)

    print(f"Starting chunking process...")
    print(f"Input file: {input_file_path}")
    print(f"Output file: {output_file_path}")
    print(f"Chunk size: ~{MAX_WORDS_PER_CHUNK} words, Overlap: {OVERLAP_WORDS} words")

    processed_lines = 0
    total_chunks_created = 0

    # We write to the new file line by line
    with open(input_file_path, 'r', encoding='utf-8') as infile, \
         open(output_file_path, 'w', encoding='utf-8') as outfile:
        
        for line in infile:
            # Skip empty lines that might exist in the original file
            line = line.strip()
            if not line:
                continue

            try:
                original_data = json.loads(line)
                transcript = original_data.get("transcript", "")
                
                if not transcript:
                    continue

                # The core logic: chunk the transcript text
                chunks = chunk_text(transcript, MAX_WORDS_PER_CHUNK, OVERLAP_WORDS)
                
                total_chunks_for_video = len(chunks)

                # For each chunk, create a new JSON entry
                for i, chunk_content in enumerate(chunks):
                    new_entry = original_data.copy() # Copy all original metadata
                    new_entry['transcript'] = None   # Remove original large transcript
                    new_entry['chunk_id'] = i + 1
                    new_entry['total_chunks'] = total_chunks_for_video
                    new_entry['chunk_text'] = chunk_content
                    
                    # Write the new, chunked entry to the output file
                    json.dump(new_entry, outfile, ensure_ascii=False)
                    outfile.write('\n')
                    total_chunks_created += 1

                processed_lines += 1

            except json.JSONDecodeError:
                print(f"Warning: Skipping malformed JSON line: {line[:100]}...")
                continue
    
    print("\n--- Chunking Summary ---")
    print(f"Processed {processed_lines} original video transcripts.")
    print(f"Created a total of {total_chunks_created} chunks.")
    print(f"Chunked data saved to: {output_file_path}")
    print("--------------------------")