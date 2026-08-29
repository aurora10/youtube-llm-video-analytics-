import { useState, useEffect } from 'react'
import './index.css'

const API_BASE = '/api'

function loadState(key, fallback) {
  try {
    const saved = JSON.parse(localStorage.getItem('yt-search-state'))
    return saved?.[key] ?? fallback
  } catch { return fallback }
}

function App() {
  const [activeTab, setActiveTab] = useState('search') // 'search', 'chat'

  // Search state
  const [keyword, setKeyword] = useState('')
  const [lang, setLang] = useState('en')
  const [maxVideos, setMaxVideos] = useState(5)
  const [loadingSearch, setLoadingSearch] = useState(false)
  const [publishedAfter, setPublishedAfter] = useState('')
  const [publishedBefore, setPublishedBefore] = useState('')


  // Chat state
  const [query, setQuery] = useState('')
  const [chatHistory, setChatHistory] = useState(() => loadState('chatHistory', {}))
  const [loadingChat, setLoadingChat] = useState(false)
  const [selectedFilename, setSelectedFilename] = useState('')
  const [chatVideoTitle, setChatVideoTitle] = useState('')

  // Search results (video thumbnails)
  const [searchResults, setSearchResults] = useState(() => loadState('searchResults', null))
  const [analyzing, setAnalyzing] = useState({}) // { [videoId]: 'loading' | 'success' | 'error' }
  const [analyzedVideos, setAnalyzedVideos] = useState(() => loadState('analyzedVideos', {}))
  const [analyzeErrors, setAnalyzeErrors] = useState(() => loadState('analyzeErrors', {}))

  // Sidebar datasets
  const [datasets, setDatasets] = useState([])

  useEffect(() => {
    fetchDatasets()
  }, [])

  // Persist state across page refreshes
  useEffect(() => {
    const state = { searchResults, analyzedVideos, analyzeErrors, chatHistory }
    try {
      localStorage.setItem('yt-search-state', JSON.stringify(state))
    } catch {}
  }, [searchResults, analyzedVideos, analyzeErrors, chatHistory])

  const fetchDatasets = async () => {
    try {
      const res = await fetch(`${API_BASE}/videos`)
      const data = await res.json()
      setDatasets(data.videos || [])
    } catch (e) {
      console.error(e)
    }
  }

  const handleDelete = async (filename, e) => {
    e.stopPropagation()
    // Delete immediately — no confirmation popup.
    // Optimistic UI: drop it from the sidebar right away for instant feedback.
    setDatasets(prev => prev.filter(v => v.filename !== filename))
    // Clear the locally-persisted conversation for this dataset.
    setChatHistory(prev => {
      if (!prev[filename]) return prev
      const next = { ...prev }
      delete next[filename]
      return next
    })
    if (selectedFilename === filename) {
      setSelectedFilename('')
      setChatVideoTitle('')
    }
    try {
      await fetch(`${API_BASE}/videos/${encodeURIComponent(filename)}`, { method: 'DELETE' })
    } catch (err) {
      alert("Delete Error: " + err.message)
    }
    // Flash / re-sync the backend's history list so the sidebar is authoritative.
    fetchDatasets()
  }

  const handleClearSearch = () => {
    setKeyword('')
    setLang('en')
    setMaxVideos(5)
    setPublishedAfter('')
    setPublishedBefore('')
    setSearchResults(null)
    setAnalyzing({})
    setAnalyzedVideos({})
    setAnalyzeErrors({})
    localStorage.removeItem('yt-search-state')
  }

  const handleSearch = async (e) => {
    e.preventDefault()
    setLoadingSearch(true)
    setSearchResults(null)
    localStorage.removeItem('yt-search-state')
    try {
      const res = await fetch(`${API_BASE}/search`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          keyword,
          lang,
          max_videos: Number(maxVideos),
          published_after: publishedAfter || undefined,
          published_before: publishedBefore || undefined,
        })
      })

      const rawText = await res.text()
      if (!rawText) {
        throw new Error(`Backend returned empty response (HTTP ${res.status})`)
      }

      let data
      try {
        data = JSON.parse(rawText)
      } catch {
        throw new Error(`Backend returned non-JSON (HTTP ${res.status}): ${rawText.slice(0, 200)}`)
      }

      if (!res.ok) {
        throw new Error(data.detail || `HTTP ${res.status}`)
      }

      if (data.status === 'success') {
        setSearchResults(data)
      } else {
        alert("Error: " + data.detail)
      }
    } catch (err) {
      alert("Error: " + err.message)
    }
    setLoadingSearch(false)
  }

  const handleAnalyze = async (videoId, title) => {
    // Prevent double-click
    if (analyzing[videoId] === 'loading') return

    setAnalyzing(prev => ({ ...prev, [videoId]: 'loading' }))

    // Clear previous error for this video
    setAnalyzeErrors(prev => { const n = { ...prev }; delete n[videoId]; return n })

    try {
      const res = await fetch(`${API_BASE}/analyze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ video_id: videoId, title: title, lang })
      })
      const data = await res.json()

      if (data.status === 'success') {
        setAnalyzing(prev => ({ ...prev, [videoId]: 'success' }))
        setAnalyzedVideos(prev => ({
          ...prev,
          [videoId]: {
            filename: data.filename,
            collection_name: data.collection_name,
            title: data.title || title,
            chunks_count: data.chunks_count,
          }
        }))

        // Auto-switch to chat with this video
        setSelectedFilename(data.filename)
        setChatVideoTitle(data.title || title)
        setChatHistory({})
        setActiveTab('chat')
        fetchDatasets()
      } else {
        setAnalyzing(prev => ({ ...prev, [videoId]: 'error' }))
        setAnalyzeErrors(prev => ({
          ...prev,
          [videoId]: {
            type: data.transcript_status || 'failed_ytdlp',
            detail: data.detail || 'Unknown error'
          }
        }))
      }
    } catch (err) {
      setAnalyzing(prev => ({ ...prev, [videoId]: 'error' }))
      setAnalyzeErrors(prev => ({
        ...prev,
        [videoId]: {
          type: 'failed_ytdlp',
          detail: err.message
        }
      }))
    }
  }

  const handleChat = async (e) => {
    e.preventDefault()
    if (!query || !selectedFilename) return

    const current = chatHistory[selectedFilename] || []
    const newChat = [...current, { role: 'user', text: query }]
    setChatHistory(prev => ({ ...prev, [selectedFilename]: newChat }))
    setLoadingChat(true)

    // Find the collection_name from analyzedVideos (stored during analyze)
    const match = Object.entries(analyzedVideos).find(([, v]) => v.filename === selectedFilename)
    const body = { query, filename: selectedFilename }
    if (match && match[1].collection_name) {
      body.collection_name = match[1].collection_name
    }

    try {
      const res = await fetch(`${API_BASE}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      })
      const data = await res.json()

      setChatHistory(prev => ({ ...prev, [selectedFilename]: [...newChat, { role: 'ai', text: data.answer, sources: data.sources }] }))
    } catch (err) {
      setChatHistory(prev => ({ ...prev, [selectedFilename]: [...newChat, { role: 'ai', text: "Error: " + err.message }] }))
    }
    setQuery('')
    setLoadingChat(false)
  }

  const selectAnalyzedVideo = (dataset) => {
    // If clicking the already-selected video while in chat, go back to search results
    if (dataset.filename === selectedFilename && activeTab === 'chat') {
      setActiveTab('search')
      return
    }
    // Find matching analyzed video info if available
    const match = Object.entries(analyzedVideos).find(([, v]) => v.filename === dataset.filename)
    setSelectedFilename(dataset.filename)
    setChatVideoTitle(match ? match[1].title : dataset.name)
    // Chat history persists across sidebar clicks; cleared only on delete
    setActiveTab('chat')
  }

  return (
    <div className="app-shell">

      {/* ---- Sidebar ---- */}
      <aside className="panel panel-side">
        <div className="brand">
          <div className="brand-mark">▶</div>
          <div>
            <div className="brand-title">YT Deep Search</div>
            <div className="brand-sub">Video Intelligence</div>
          </div>
        </div>

        <button
          className={`btn ${activeTab === 'chat' ? 'btn-back' : 'btn-primary'} btn-block`}
          onClick={() => { localStorage.removeItem('yt-search-state'); setActiveTab('search') }}
        >
          {activeTab === 'chat' ? (
            <><span>←</span> Back to search</>
          ) : (
            <><span>+</span> New Search</>
          )}
        </button>

        <div className="sidebar-scroll">
          <h3 className="section-label" style={{ marginTop: '1.5rem' }}>Analyzed Videos</h3>
          {datasets.length === 0 && (
            <p className="empty-note">No analyzed videos yet.</p>
          )}
          <div className="dataset-list">
            {datasets.map(v => (
              <div
                key={v.filename}
                onClick={() => selectAnalyzedVideo(v)}
                className={`dataset-item${selectedFilename === v.filename ? ' active' : ''}`}
              >
                <div className="dataset-name">{v.name}</div>
                <button
                  className="icon-btn"
                  onClick={(e) => handleDelete(v.filename, e)}
                  title="Delete dataset"
                  aria-label={`Delete ${v.name}`}
                >🗑️</button>
              </div>
            ))}
          </div>
        </div>
      </aside>

      {/* ---- Main Area ---- */}
      <main className="panel panel-main">

        {activeTab === 'search' && (
          <div className="search-scroll tab-fade">
            <div className="search-head">
              <h1 className="search-title">New Deep Search</h1>
              <p className="search-sub">Find videos beyond the recommendation algorithm and analyze their transcripts.</p>
            </div>

            <form onSubmit={handleSearch} className="form-grid">
              <div className="field">
                <label className="field-label">Keyword / Prompt</label>
                <input
                  type="text"
                  className="input"
                  value={keyword}
                  onChange={e => setKeyword(e.target.value)}
                  placeholder="Enter topic to research..."
                  required
                />
              </div>

              <div className="form-grid-4">
                <div className="field">
                  <label className="field-label">Language</label>
                  <select className="select" value={lang} onChange={e => setLang(e.target.value)}>
                    <option value="en">English (en)</option>
                    <option value="es">Spanish (es)</option>
                    <option value="ru">Russian (ru)</option>
                  </select>
                </div>
                <div className="field">
                  <label className="field-label">Max Videos</label>
                  <input
                    type="number"
                    className="input"
                    value={maxVideos}
                    onChange={e => setMaxVideos(e.target.value)}
                    min="1" max="100"
                  />
                </div>
                <div className="field">
                  <label className="field-label">Published After</label>
                  <input
                    type="date"
                    className="input"
                    value={publishedAfter}
                    onChange={e => setPublishedAfter(e.target.value)}
                  />
                </div>
                <div className="field">
                  <label className="field-label">Published Before</label>
                  <input
                    type="date"
                    className="input"
                    value={publishedBefore}
                    onChange={e => setPublishedBefore(e.target.value)}
                  />
                </div>
              </div>

              {loadingSearch ? (
                <div className="loading-center">
                  <div className="spinner"></div>
                  <p style={{ color: 'var(--text-muted)' }}>Searching YouTube...</p>
                </div>
              ) : (
                <div className="form-actions">
                  <button type="submit" className="btn btn-primary">Search</button>
                  <button type="button" className="btn btn-ghost" onClick={handleClearSearch}>Clear</button>
                </div>
              )}
            </form>

            {/* Search Results: Video Thumbnails with Analyze Buttons */}
            {searchResults && !loadingSearch && (
              <div className="results">
                <div className="results-head">
                  <div>
                    <h3>
                      <span className="accent">📊</span> Found {searchResults.videos_found} videos for "{searchResults.keyword}"
                    </h3>
                    <p className="results-sub">
                      Click <span style={{ color: 'var(--accent-3)' }}>Analyze</span> on a video to download & index its transcript.
                    </p>
                  </div>
                </div>

                <div className="results-grid">
                  {searchResults.video_details.map(v => {
                    const vid = v.video_id
                    const isAnalyzed = analyzedVideos[vid]
                    const isAnalyzing = analyzing[vid] === 'loading'
                    const isError = analyzing[vid] === 'error'

                    return (
                      <div
                        key={vid}
                        className={`result-card${isAnalyzed ? ' is-analyzed' : ''}`}
                      >
                        {/* Thumbnail */}
                        {v.thumbnail_url ? (
                          <img src={v.thumbnail_url} alt="" className="thumb" />
                        ) : (
                          <div className="thumb-fallback">▶</div>
                        )}

                        {/* Info — title gets the full remaining width; button sits below */}
                        <div className="result-info">
                          <a
                            href={`https://www.youtube.com/watch?v=${vid}`}
                            target="_blank"
                            rel="noreferrer"
                            className="result-title"
                            title={v.title || vid}
                          >
                            {v.title || vid}
                          </a>
                          <div className="result-meta">
                            <span>{v.published_date?.slice(0, 10)}</span>
                          </div>

                          {/* Inline error message */}
                          {isError && analyzeErrors[vid] && (
                            <div className={`alert-inline ${analyzeErrors[vid].type === 'no_transcript' ? 'info' : 'warn'}`}>
                              <span>{analyzeErrors[vid].type === 'no_transcript' ? 'ℹ️' : '⚠️'}</span>
                              <span>{analyzeErrors[vid].detail}</span>
                            </div>
                          )}

                          {/* Analyze Button */}
                          <div className="result-actions">
                            {isAnalyzed ? (
                              <button
                                className="btn btn-success"
                                style={{ padding: '0.45rem 0.7rem', fontSize: '0.78rem' }}
                                onClick={() => {
                                  setSelectedFilename(isAnalyzed.filename)
                                  setChatVideoTitle(isAnalyzed.title)
                                  setChatHistory({})
                                  setActiveTab('chat')
                                }}
                              >
                                ✅ Chat
                              </button>
                            ) : isError ? (
                              <button
                                className="btn btn-danger"
                                style={{ padding: '0.45rem 0.7rem', fontSize: '0.78rem' }}
                                onClick={() => handleAnalyze(vid, v.title)}
                              >
                                {analyzeErrors[vid]?.type === 'no_transcript' ? '🔍 Analyze' : '❌ Retry'}
                              </button>
                            ) : (
                              <button
                                className="btn btn-tonal"
                                style={{ padding: '0.45rem 0.7rem', fontSize: '0.78rem' }}
                                onClick={() => handleAnalyze(vid, v.title)}
                                disabled={isAnalyzing}
                              >
                                {isAnalyzing ? (
                                  <span style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                                    <span className="spinner inline"></span>
                                    Analyzing
                                  </span>
                                ) : '🔍 Analyze'}
                              </button>
                            )}
                          </div>
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
            )}
          </div>
        )}

        {activeTab === 'chat' && (
          <div className="chat-col tab-fade">
            <div className="chat-head">
              <h2 className="chat-head-title">
                <span>💬</span>
                <span>
                  Chat: <span className="accent" style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    {chatVideoTitle || selectedFilename.replace('_chunked.jsonl', '')}
                  </span>
                </span>
              </h2>
              {!selectedFilename && (
                <span className="chat-head-hint">Select an analyzed video from the sidebar</span>
              )}
            </div>

            <div className="chat-scroll">
              {!selectedFilename || !chatHistory[selectedFilename]?.length ? (
                <p className="chat-empty">
                  {selectedFilename
                    ? 'Ask a question about this video transcript.'
                    : 'Analyze a video first, then come back to chat.'}
                </p>
              ) : null}

              {(chatHistory[selectedFilename] || []).map((msg, i) => (
                <div key={i} className={`msg ${msg.role === 'user' ? 'user' : 'ai'}`}>
                  <div className="msg-role">
                    {msg.role === 'user' ? 'You' : 'AI Assistant'}
                  </div>
                  <div className="msg-body">{msg.text}</div>

                  {msg.sources && msg.sources.length > 0 && (
                    <div className="msg-sources">
                      <div className="msg-sources-label">Sources:</div>
                      <div className="msg-sources-list">
                        {Array.from(new Set(msg.sources.map(s => s.video_id))).map(vid => {
                          const source = msg.sources.find(s => s.video_id === vid)
                          return (
                            <a
                              key={vid}
                              href={`https://www.youtube.com/watch?v=${vid}`}
                              target="_blank"
                              rel="noreferrer"
                              className="video-link"
                            >
                              <span className="play">▶</span> {source?.title || `Video ${vid}`}
                            </a>
                          )
                        })}
                      </div>
                    </div>
                  )}
                </div>
              ))}
              {loadingChat && <div className="spinner inline" style={{ alignSelf: 'flex-start', margin: '0 0 0 1rem' }}></div>}
            </div>

            <form onSubmit={handleChat} className="chat-composer">
              <input
                type="text"
                className="input"
                value={query}
                onChange={e => setQuery(e.target.value)}
                placeholder={selectedFilename ? "Chat with video data..." : "Select a video first..."}
                disabled={loadingChat || !selectedFilename}
              />
              <button
                type="submit"
                className="chat-send"
                disabled={loadingChat || !selectedFilename}
              >
                Send
              </button>
            </form>
          </div>
        )}
      </main>
    </div>
  )
}

export default App
