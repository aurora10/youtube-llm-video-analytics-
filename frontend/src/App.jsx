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
    const name = filename.replace('_chunked.jsonl', '')
    if (!confirm(`Delete "${name}"?`)) return
    try {
      await fetch(`${API_BASE}/videos/${encodeURIComponent(filename)}`, { method: 'DELETE' })
      if (selectedFilename === filename) {
        setSelectedFilename('')
        setChatVideoTitle('')
      }
      fetchDatasets()
    } catch (err) {
      alert("Delete Error: " + err.message)
    }
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
    <div style={{ display: 'flex', gap: '2rem', height: '90vh' }}>

      {/* Sidebar */}
      <div className="glass-panel" style={{ width: '300px', padding: '1rem', display: 'flex', flexDirection: 'column' }}>
        <h2 className="text-neon-cyan" style={{ margin: '0 0 1rem 0' }}>YT Deep Search</h2>

        <button className="btn-neon" onClick={() => { localStorage.removeItem('yt-search-state'); setActiveTab('search') }} style={{ marginBottom: '1rem', width: '100%' }}>
          + New Search
        </button>

        <div style={{ flex: 1, overflowY: 'auto' }}>
          <h3 style={{ color: '#888', fontSize: '0.9rem', textTransform: 'uppercase', marginBottom: '0.5rem' }}>
            Analyzed Videos
          </h3>
          {datasets.length === 0 && (
            <p style={{ color: '#555', fontSize: '0.9rem' }}>No analyzed videos yet.</p>
          )}
          {datasets.map(v => (
            <div
              key={v.filename}
              onClick={() => selectAnalyzedVideo(v)}
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                padding: '0.8rem',
                margin: '0.5rem 0',
                backgroundColor: selectedFilename === v.filename ? 'rgba(0, 255, 255, 0.1)' : 'rgba(255,255,255,0.02)',
                borderRadius: '8px',
                cursor: 'pointer',
                borderLeft: selectedFilename === v.filename ? '4px solid #00ffff' : '4px solid transparent',
                transition: 'all 0.2s'
              }}
            >
              <div style={{ fontWeight: '500', fontSize: '0.85rem', wordBreak: 'break-word' }}>{v.name}</div>
              <button
                onClick={(e) => handleDelete(v.filename, e)}
                style={{
                  background: 'none', border: 'none', color: '#ff4444', cursor: 'pointer',
                  fontSize: '1.1rem', padding: '0 0.3rem', lineHeight: 1, opacity: 0.6,
                  transition: 'opacity 0.2s', flexShrink: 0, marginLeft: '0.3rem',
                }}
                onMouseEnter={e => e.currentTarget.style.opacity = '1'}
                onMouseLeave={e => e.currentTarget.style.opacity = '0.6'}
                title="Delete dataset"
              >🗑️</button>
            </div>
          ))}
        </div>
      </div>

      {/* Main Area */}
      <div className="glass-panel" style={{ flex: 1, padding: '2rem', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>

        {activeTab === 'search' && (
          <div style={{ maxWidth: '800px', margin: '0 auto', width: '100%', overflowY: 'auto', paddingBottom: '2rem' }}>
            <h1 style={{ marginBottom: '2rem', fontSize: '2rem' }}>New Deep Search</h1>
            <form onSubmit={handleSearch} style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
              <div>
                <label style={{ display: 'block', marginBottom: '0.5rem', color: '#aaa', fontSize: '0.9rem' }}>Keyword / Prompt</label>
                <input
                  type="text"
                  className="input-glass"
                  value={keyword}
                  onChange={e => setKeyword(e.target.value)}
                  placeholder="Enter topic to research..."
                  required
                />
              </div>
              <div style={{ display: 'flex', gap: '1rem' }}>
                <div style={{ flex: 1 }}>
                  <label style={{ display: 'block', marginBottom: '0.5rem', color: '#aaa', fontSize: '0.9rem' }}>Language</label>
                  <select className="input-glass select-glass" value={lang} onChange={e => setLang(e.target.value)}>
                    <option value="en">English (en)</option>
                    <option value="es">Spanish (es)</option>
                    <option value="ru">Russian (ru)</option>
                  </select>
                </div>
                <div style={{ flex: 1 }}>
                  <label style={{ display: 'block', marginBottom: '0.5rem', color: '#aaa', fontSize: '0.9rem' }}>Max Videos</label>
                  <input
                    type="number"
                    className="input-glass"
                    value={maxVideos}
                    onChange={e => setMaxVideos(e.target.value)}
                    min="1" max="100"
                  />
                </div>
              </div>

              <div style={{ display: 'flex', gap: '1rem' }}>
                <div style={{ flex: 1 }}>
                  <label style={{ display: 'block', marginBottom: '0.5rem', color: '#aaa', fontSize: '0.9rem' }}>Published After</label>
                  <input
                    type="date"
                    className="input-glass"
                    value={publishedAfter}
                    onChange={e => setPublishedAfter(e.target.value)}
                  />
                </div>
                <div style={{ flex: 1 }}>
                  <label style={{ display: 'block', marginBottom: '0.5rem', color: '#aaa', fontSize: '0.9rem' }}>Published Before</label>
                  <input
                    type="date"
                    className="input-glass"
                    value={publishedBefore}
                    onChange={e => setPublishedBefore(e.target.value)}
                  />
                </div>
              </div>

              {loadingSearch ? (
                <div style={{ textAlign: 'center', marginTop: '2rem' }}>
                  <div className="spinner"></div>
                  <p className="text-neon-cyan">Searching YouTube...</p>
                </div>
              ) : (
                <div style={{ display: 'flex', gap: '1rem', marginTop: '1rem' }}>
                  <button type="submit" className="btn-neon" style={{ padding: '1rem', flex: 1 }}>SEARCH</button>
                  <button
                    type="button"
                    className="btn-neon"
                    onClick={handleClearSearch}
                    style={{
                      padding: '1rem',
                      flex: 1,
                      borderColor: '#888',
                      color: '#888',
                      boxShadow: 'inset 0 0 0.4em 0 #888, 0 0 0.4em 0 #888',
                    }}
                  >
                    CLEAR
                  </button>
                </div>
              )}
            </form>

            {/* Search Results: Video Thumbnails with Analyze Buttons */}
            {searchResults && !loadingSearch && (
              <div style={{ marginTop: '2rem', borderTop: '1px solid rgba(255,255,255,0.15)', paddingTop: '1.5rem' }}>
                <div style={{ marginBottom: '1.5rem' }}>
                  <h3 style={{ margin: 0, color: '#00ffff', fontSize: '1.2rem' }}>
                    📊 Found {searchResults.videos_found} videos for "{searchResults.keyword}"
                  </h3>
                  <p style={{ color: '#888', fontSize: '0.85rem', margin: '0.3rem 0 0 0' }}>
                    Click <span style={{ color: '#00ffff' }}>Analyze</span> on a video to download & index its transcript.
                  </p>
                </div>

                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(380px, 1fr))', gap: '0.8rem' }}>
                  {searchResults.video_details.map(v => {
                    const vid = v.video_id
                    const isAnalyzed = analyzedVideos[vid]
                    const isAnalyzing = analyzing[vid] === 'loading'
                    const isError = analyzing[vid] === 'error'

                    return (
                      <div
                        key={vid}
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          gap: '0.8rem',
                          padding: '0.7rem',
                          borderRadius: '10px',
                          backgroundColor: isAnalyzed ? 'rgba(0,255,0,0.06)' : 'rgba(255,255,255,0.02)',
                          border: isAnalyzed ? '1px solid rgba(0,255,0,0.3)' : '1px solid rgba(255,255,255,0.08)',
                          transition: 'all 0.2s',
                        }}
                      >
                        {/* Thumbnail */}
                        {v.thumbnail_url ? (
                          <img
                            src={v.thumbnail_url}
                            alt=""
                            style={{
                              width: '120px', height: '68px', borderRadius: '6px',
                              objectFit: 'cover', flexShrink: 0,
                            }}
                          />
                        ) : (
                          <div style={{
                            width: '120px', height: '68px', borderRadius: '6px',
                            backgroundColor: 'rgba(255,255,255,0.05)', flexShrink: 0,
                            display: 'flex', alignItems: 'center', justifyContent: 'center',
                            fontSize: '1.5rem',
                          }}>▶</div>
                        )}

                        {/* Info */}
                        <div style={{ minWidth: 0, flex: 1 }}>
                          <a
                            href={`https://www.youtube.com/watch?v=${vid}`}
                            target="_blank"
                            rel="noreferrer"
                            style={{
                              fontWeight: 600, fontSize: '0.85rem', color: '#ddd',
                              textDecoration: 'none', display: 'block',
                              whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                              marginBottom: '0.2rem',
                            }}
                            onMouseEnter={e => e.currentTarget.style.color = '#00ffff'}
                            onMouseLeave={e => e.currentTarget.style.color = '#ddd'}
                          >
                            {v.title || vid}
                          </a>
                          <div style={{ fontSize: '0.7rem', color: '#888' }}>{v.published_date?.slice(0, 10)}</div>
                        </div>

                        {/* Inline error message */}
                        {isError && analyzeErrors[vid] && (
                          <div style={{
                            marginTop: '0.4rem',
                            padding: '0.5rem 0.7rem',
                            borderRadius: '6px',
                            fontSize: '0.75rem',
                            lineHeight: 1.4,
                            backgroundColor: analyzeErrors[vid].type === 'no_transcript'
                              ? 'rgba(0, 255, 200, 0.06)'
                              : 'rgba(255, 80, 80, 0.06)',
                            borderLeft: analyzeErrors[vid].type === 'no_transcript'
                              ? '3px solid rgba(0, 255, 200, 0.5)'
                              : '3px solid rgba(255, 80, 80, 0.5)',
                            color: analyzeErrors[vid].type === 'no_transcript' ? '#7fccb7' : '#cc8888',
                          }}>
                            {analyzeErrors[vid].type === 'no_transcript' ? 'ℹ️ ' : '⚠️ '}
                            {analyzeErrors[vid].detail}
                          </div>
                        )}

                        {/* Analyze Button */}
                        {isAnalyzed ? (
                          <button
                            className="btn-neon"
                            style={{
                              padding: '0.4em 1em', fontSize: '0.8rem',
                              borderColor: '#39ff14', color: '#39ff14',
                              boxShadow: 'inset 0 0 0.4em 0 #39ff14, 0 0 0.4em 0 #39ff14',
                              whiteSpace: 'nowrap', flexShrink: 0,
                            }}
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
                            className="btn-neon"
                            style={{
                              padding: '0.4em 1em', fontSize: '0.8rem',
                              borderColor: '#ff5555', color: '#ff5555',
                              whiteSpace: 'nowrap', flexShrink: 0,
                            }}
                            onClick={() => handleAnalyze(vid, v.title)}
                          >
                            {analyzeErrors[vid]?.type === 'no_transcript' ? '🔍 Analyze' : '❌ Retry'}
                          </button>
                        ) : (
                          <button
                            className="btn-neon"
                            style={{
                              padding: '0.4em 1em', fontSize: '0.8rem',
                              whiteSpace: 'nowrap', flexShrink: 0,
                            }}
                            onClick={() => handleAnalyze(vid, v.title)}
                            disabled={isAnalyzing}
                          >
                            {isAnalyzing ? (
                              <span style={{ display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
                                <span className="spinner" style={{ width: '14px', height: '14px', borderWidth: '2px', margin: 0 }}></span>
                                ...
                              </span>
                            ) : '🔍 Analyze'}
                          </button>
                        )}
                      </div>
                    )
                  })}
                </div>
              </div>
            )}
          </div>
        )}

        {activeTab === 'chat' && (
          <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
            <h2 style={{ margin: 0, paddingBottom: '1rem', borderBottom: '1px solid rgba(255,255,255,0.1)', display: 'flex', justifyContent: 'space-between' }}>
              <span>
                Chat: <span className="text-neon-cyan">
                  {chatVideoTitle || selectedFilename.replace('_chunked.jsonl', '')}
                </span>
              </span>
              {!selectedFilename && (
                <span style={{ fontSize: '0.85rem', color: '#ff5555' }}>Select an analyzed video from the sidebar</span>
              )}
            </h2>

            <div style={{ flex: 1, overflowY: 'auto', padding: '1rem 0', display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
              {!selectedFilename || !chatHistory[selectedFilename]?.length ? (
                <p style={{ color: '#555', textAlign: 'center', marginTop: '2rem' }}>
                  {selectedFilename
                    ? 'Ask a question about this video transcript.'
                    : 'Analyze a video first, then come back to chat.'}
                </p>
              ) : null}

              {(chatHistory[selectedFilename] || []).map((msg, i) => (
                <div key={i} style={{
                  alignSelf: msg.role === 'user' ? 'flex-end' : 'flex-start',
                  backgroundColor: msg.role === 'user' ? 'rgba(255,255,255,0.1)' : 'rgba(0,255,255,0.05)',
                  border: msg.role === 'ai' ? '1px solid rgba(0,255,255,0.2)' : 'none',
                  padding: '1.5rem',
                  borderRadius: '12px',
                  maxWidth: '80%',
                  boxShadow: msg.role === 'ai' ? '0 0 15px rgba(0,255,255,0.05)' : 'none'
                }}>
                  <div style={{ fontSize: '0.8rem', color: msg.role === 'user' ? '#ccc' : '#00ffff', marginBottom: '0.8rem', textTransform: 'uppercase', letterSpacing: '1px' }}>
                    {msg.role === 'user' ? 'You' : 'AI Assistant'}
                  </div>
                  <div style={{ whiteSpace: 'pre-wrap', lineHeight: '1.6' }}>{msg.text}</div>

                  {msg.sources && msg.sources.length > 0 && (
                    <div style={{ marginTop: '1.5rem', paddingTop: '1rem', borderTop: '1px solid rgba(0,255,255,0.1)' }}>
                      <div style={{ fontSize: '0.8rem', color: '#00ffff', marginBottom: '0.8rem', textTransform: 'uppercase', letterSpacing: '1px' }}>Sources:</div>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                        {Array.from(new Set(msg.sources.map(s => s.video_id))).map(vid => {
                          const source = msg.sources.find(s => s.video_id === vid)
                          return (
                            <a
                              key={vid}
                              href={`https://www.youtube.com/watch?v=${vid}`}
                              target="_blank"
                              rel="noreferrer"
                              className="video-link"
                              style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.9rem' }}
                            >
                              <span style={{ fontSize: '0.7rem' }}>▶</span> {source?.title || `Video ${vid}`}
                            </a>
                          )
                        })}
                      </div>
                    </div>
                  )}
                </div>
              ))}
              {loadingChat && <div className="spinner" style={{ width: '24px', height: '24px', borderWidth: '2px', alignSelf: 'flex-start', margin: '0 0 0 1rem' }}></div>}
            </div>

            <form onSubmit={handleChat} style={{ display: 'flex', gap: '1rem', marginTop: '1rem', borderTop: '1px solid rgba(255,255,255,0.1)', paddingTop: '1rem' }}>
              <input
                type="text"
                className="input-glass"
                value={query}
                onChange={e => setQuery(e.target.value)}
                placeholder={selectedFilename ? "Chat with video data..." : "Select a video first..."}
                disabled={loadingChat || !selectedFilename}
                style={{ padding: '1rem' }}
              />
              <button type="submit" className="btn-neon" disabled={loadingChat || !selectedFilename} style={{ padding: '0 2rem' }}>SEND</button>
            </form>
          </div>
        )}
      </div>
    </div>
  )
}

export default App