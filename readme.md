This app is for deep search on YT videos.
YT search engine pushes reslults it thinks best for user. Users has no control over the results.

However with YT api we can get big list of video urls based on search keyword. We can get huge amount of results, 
wich is better than YT search that gives only limited numer of results and user has no control over it.

However we cannot watch hundereds of videos to do our reseach. 
THis app does the following:
- Gets URL's of videos for a given search.
- Extracts video transcripts for each video and saves them into json file together wiht metadata.
- Uses LLM to answer the questions:
    - Do these videos contain informaion on the subject we are looking for?
    - How deeply covered the jubject

- Produces the ranked shorlist of YT URLs fot the user to watch.

# current file:
- LLM_ready.py - gets video data with YT API - fails often
- LLM_ready_YT_DLP.py - does the same, only with yt-dlp, slow but much better resuls

- chunk_processor.py  - chunks the results for LLM friendly format. Asks for input file path and saves to OUTPUT folder.
- rag_proccessor.py - tokenizes the previous files -> builds the query and sends it to LLM for conversation
  


  
example to run LLM_ready_YT_DLP.py:

1. python LLM_ready_YT_DLP.py -k "депорт украинцев из сша" -l "en" -m 10 -w 3 // 10 results in 3 weeks
or
python LLM_ready_YT_DLP.py -k "депорт украинцев из сша" -l "ru" -m 10 -w 3 // 10 results in 3 weeks




example to run rag_proccessor.py:

python rag_processor.py --file OUTPUT/deportation_of_ukranians_from_us.jsonl_chunked.jsonl
// collection name is now optional and auto-generated from the filename.
// You can still override it with --collection-name if needed.




