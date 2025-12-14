import chromadb
import json
import os
import openai
from sentence_transformers import SentenceTransformer
import textwrap
import argparse
import re
from dotenv import load_dotenv

# --- Configuration ---
load_dotenv('.env.local')
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Initialize ChromaDB client. 'PersistentClient' saves the DB to disk.
client = chromadb.PersistentClient(path="./chroma_db")

# Initialize the embedding model
print("Loading embedding model (this may take a moment on first run)...")
embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
print("Embedding model loaded.")

# --- Initialize the LLM client using the hardcoded key ---
### MODIFICATION HERE: We now pass the key directly to the client ###
try:
    if not OPENAI_API_KEY:
        print("\n---FATAL ERROR---")
        print("OpenAI API key is missing.")
        print("Please check your .env.local file.")
        exit()
        
    llm_client = openai.OpenAI(api_key=OPENAI_API_KEY)
    # A simple check to see if the key is valid
    llm_client.models.list() 
    print("OpenAI client initialized successfully.")
except openai.AuthenticationError:
    print("\n---FATAL ERROR---")
    print("The provided OpenAI API key is invalid or expired.")
    print("Please check the key in the 'OPENAI_API_KEY' variable.")
    exit()
except Exception as e:
    print(f"An unexpected error occurred while initializing the OpenAI client: {e}")
    exit()


# --- Phase 1: Indexing Function ---
def build_or_load_index(chunked_jsonl_file: str, collection_name: str):
    """
    Loads data from the chunked JSONL file and indexes it into ChromaDB.
    If the collection already exists and has data, it skips indexing.
    """
    try:
        collection = client.get_or_create_collection(name=collection_name)
        
        if collection.count() > 0:
            print(f"Collection '{collection_name}' already loaded with {collection.count()} chunks. Ready to chat.")
            return collection

    except Exception as e:
        print(f"Error connecting to ChromaDB or getting collection: {e}")
        return None

    print(f"Collection '{collection_name}' is empty. Indexing data from '{chunked_jsonl_file}'...")
    if not os.path.exists(chunked_jsonl_file):
        print(f"Error: Chunked data file not found at '{chunked_jsonl_file}'.")
        return None

    documents, metadatas, ids = [], [], []
    with open(chunked_jsonl_file, 'r', encoding='utf-8') as f:
        for line in f:
            if not line.strip(): continue
            data = json.loads(line)
            chunk_text = data.get('chunk_text')
            if not chunk_text: continue

            documents.append(chunk_text)
            metadatas.append({"video_id": data.get("video_id"), "title": data.get("title"), "chunk_id": data.get("chunk_id"), "published_date": data.get("published_date")})
            ids.append(f"{data.get('video_id')}_{data.get('chunk_id')}")

    if not documents:
        print("No documents found to index.")
        return collection

    print(f"Generating embeddings for {len(documents)} document chunks...")
    embeddings = embedding_model.encode(documents, show_progress_bar=True).tolist()

    print("Adding data to ChromaDB in batches...")
    batch_size = 100
    for i in range(0, len(documents), batch_size):
        collection.add(
            embeddings=embeddings[i:i+batch_size],
            documents=documents[i:i+batch_size],
            metadatas=metadatas[i:i+batch_size],
            ids=ids[i:i+batch_size]
        )

    print(f"Indexing complete. Total chunks indexed: {collection.count()}. Ready to chat.")
    return collection

# --- Phase 2: Querying Function (Unchanged) ---
def query_rag_system(query: str, collection, k: int = 5):
    """
    Takes a user query, retrieves relevant context, and generates an answer.
    """
    if not query:
        return "Please enter a question.", []

    query_embedding = embedding_model.encode(query).tolist()
    
    results = collection.query(query_embeddings=[query_embedding], n_results=k)
    
    retrieved_docs = results['documents'][0]
    retrieved_metadatas = results['metadatas'][0]

    if not retrieved_docs:
        return "I could not find any relevant information in the video transcripts to answer your question.", []
        
    context_str = ""
    for i, (doc, meta) in enumerate(zip(retrieved_docs, retrieved_metadatas)):
        context_str += f"Source {i+1} (Video ID: {meta.get('video_id', 'N/A')}, Title: {meta.get('title', 'N/A')}):\n"
        context_str += f'"{doc}"\n\n'

    prompt_template = f"""
    You are an AI assistant analyzing YouTube video transcripts.
    Use ONLY the information from the 'CONTEXT' below to answer the 'USER QUESTION'.
    Do not use any outside knowledge. Your answer must be grounded in the provided text.
    After your answer, cite the sources you used in a 'Sources:' section, referencing the Video ID and Title.

    CONTEXT:
    {context_str}

    USER QUESTION:
    {query}

    ANSWER:
    """

    print("\n🤖 Thinking...")
    try:
        response = llm_client.chat.completions.create(
            model="gpt-5-mini",
            messages=[
                {"role": "system", "content": "You are a helpful research assistant specialized in analyzing provided text."},
                {"role": "user", "content": prompt_template}
            ],
            temperature=1,
        )
        final_answer = response.choices[0].message.content
        return final_answer, retrieved_metadatas
    except Exception as e:
        error_message = f"An error occurred while communicating with the LLM: {e}"
        return error_message, []


# --- Main Execution Logic with Interactive Loop ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="A RAG system for querying YouTube video transcripts.")
    parser.add_argument(
        "--file", 
        default=os.path.join("llm_data", "TPS_для_украинцев.jsonl_chunked.jsonl"), 
        help="Path to the chunked JSONL file containing transcript data."
    )
    parser.add_argument(
        "--collection-name", 
        default=None, 
        help="Name of the ChromaDB collection to use. If not provided, it will be derived from the filename."
    )
    args = parser.parse_args()

    collection_name = args.collection_name
    if not collection_name:
        # Derive collection name from filename
        base_name = os.path.basename(args.file)
        # Remove extension (handle .jsonl_chunked.jsonl or just .jsonl)
        name_without_ext = base_name.replace(".jsonl", "").replace("_chunked", "")
        
        # Sanitize: replace non-alphanumeric with underscores (ChromaDB requirement)
        # ChromaDB requires: 3-63 characters, starts and ends with alphanumeric, contains only alphanumeric, underscores, hyphens, dots
        sanitized_name = re.sub(r'[^a-zA-Z0-9_.-]', '_', name_without_ext)
        
        # Ensure it starts/ends with alphanumeric
        sanitized_name = re.sub(r'^[^a-zA-Z0-9]+', '', sanitized_name)
        sanitized_name = re.sub(r'[^a-zA-Z0-9]+$', '', sanitized_name)
        
        # Truncate to 63 chars
        collection_name = sanitized_name[:63]
        
        # Fallback if empty or too short
        if len(collection_name) < 3:
            collection_name = f"collection_{collection_name}".ljust(3, '_')

        print(f"Auto-generated collection name: '{collection_name}'")

    collection = build_or_load_index(args.file, collection_name)

    if collection:
        print("\n=======================================================")
        print("    🔎 YouTube Transcript RAG System Initialized 🔎")
        print("=======================================================")
        print(f"Corpus: {os.path.basename(args.file)}")
        print("Ask a question about the indexed transcripts.")
        print("Type 'exit' or 'quit' to end the session.")
        
        while True:
            try:
                user_question = input("\n👤 Your Question: ")

                if user_question.lower() in ['exit', 'quit']:
                    print("\n👋 Goodbye!")
                    break
                
                if not user_question.strip():
                    continue

                answer, sources = query_rag_system(user_question, collection)
                
                print("\n\n💬 AI Answer:")
                print("-------------------------------------------------------")
                print(textwrap.fill(answer, width=100))
                print("-------------------------------------------------------")

                if sources:
                    print("\n📚 Sources Used for this Answer:")
                    printed_sources = set()
                    for i, meta in enumerate(sources):
                        source_id = meta.get('video_id')
                        if source_id not in printed_sources:
                            print(f"  - [Video ID: {source_id}] Title: {meta.get('title')}")
                            printed_sources.add(source_id)

            except KeyboardInterrupt:
                print("\n\n👋 Exiting program. Goodbye!")
                break
            except Exception as e:
                print(f"\nAn unexpected error occurred in the main loop: {e}")
                break