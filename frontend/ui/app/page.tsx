'use client'

import { FormEvent, useEffect, useState } from 'react'
import {
  ArrowLeft, Check, ChevronDown, FileVideo, Loader2, MessageSquare,
  Paperclip, Play, Plus, Search, Send, Settings2, Sparkles, Trash2,
} from 'lucide-react'

const API_BASE = '/api'

function loadState(key: string, fallback: unknown) {
  try {
    const saved = JSON.parse(localStorage.getItem('yt-search-state') || 'null')
    return saved?.[key] ?? fallback
  } catch {
    return fallback
  }
}

type ChatMessage = { role: 'user' | 'assistant'; text: string; sources?: { video_id: string; title?: string }[] }

export default function Page() {
  const [view, setView] = useState<'search' | 'chat'>('search')

  // Search state
  const [keyword, setKeyword] = useState('')
  const [lang, setLang] = useState('en')
  const [maxVideos, setMaxVideos] = useState('5')
  const [loadingSearch, setLoadingSearch] = useState(false)
  const [publishedAfter, setPublishedAfter] = useState('')
  const [publishedBefore, setPublishedBefore] = useState('')

  // Chat state
  const [draft, setDraft] = useState('')
  const [chatHistory, setChatHistory] = useState<Record<string, ChatMessage[]>>(() => loadState('chatHistory', {}))
  const [loadingChat, setLoadingChat] = useState(false)
  const [selectedFilename, setSelectedFilename] = useState<string>(() => loadState('selectedFilename', ''))
  const [chatVideoTitle, setChatVideoTitle] = useState<string>(() => loadState('chatVideoTitle', ''))

  // Search results & analysis status
  const [searchResults, setSearchResults] = useState<any>(() => loadState('searchResults', null))
  const [analyzing, setAnalyzing] = useState<Record<string, string>>({})
  const [analyzedVideos, setAnalyzedVideos] = useState<Record<string, any>>(() => loadState('analyzedVideos', {}))
  const [analyzeErrors, setAnalyzeErrors] = useState<Record<string, any>>(() => loadState('analyzeErrors', {}))
  const [datasets, setDatasets] = useState<any[]>([])
  const [suggestions, setSuggestions] = useState<string[]>([])
  const [suggestLoading, setSuggestLoading] = useState(false)

  useEffect(() => { fetchDatasets() }, [])

  useEffect(() => {
    const h = window.location.hash
    if (h === '#chat') setView('chat')
  }, [])

  // Regenerate context-aware question suggestions whenever the video changes.
  useEffect(() => {
    if (!selectedFilename) return
    let cancelled = false
    setSuggestLoading(true)
    ;(async () => {
      try {
        const match = Object.entries(analyzedVideos).find(([, v]) => v.filename === selectedFilename)
        const body: Record<string, any> = { filename: selectedFilename }
        if (match && match[1].collection_name) body.collection_name = match[1].collection_name
        const res = await fetch(`${API_BASE}/suggest`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        })
        if (cancelled) return
        const data = await res.json()
        if (data?.suggestions?.length) setSuggestions(data.suggestions)
      } catch {
        // keep current suggestions on failure
      } finally {
        if (!cancelled) setSuggestLoading(false)
      }
    })()
    return () => { cancelled = true }
  }, [selectedFilename, analyzedVideos])

  useEffect(() => {
    const state = { searchResults, analyzedVideos, analyzeErrors, chatHistory, selectedFilename, chatVideoTitle }
    try { localStorage.setItem('yt-search-state', JSON.stringify(state)) } catch {}
  }, [searchResults, analyzedVideos, analyzeErrors, chatHistory, selectedFilename, chatVideoTitle])

  const fetchDatasets = async () => {
    try {
      const res = await fetch(`${API_BASE}/videos`)
      const data = await res.json()
      setDatasets(data.videos || [])
    } catch (e) {
      console.error(e)
    }
  }

  const handleDelete = async (filename: string, e: React.MouseEvent) => {
    e.stopPropagation()
    // Delete immediately — no confirmation popup.
    setDatasets((prev) => prev.filter((v) => v.filename !== filename))
    setAnalyzedVideos((prev) => {
      const next = { ...prev }
      for (const [k, v] of Object.entries(next)) {
        if (v?.filename === filename) delete next[k]
      }
      return next
    })
    setChatHistory((prev) => {
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
      alert('Delete Error: ' + (err as Error).message)
    }
    fetchDatasets()
  }

  const handleClearSearch = () => {
    setKeyword('')
    setLang('en')
    setMaxVideos('5')
    setPublishedAfter('')
    setPublishedBefore('')
    setSearchResults(null)
    setAnalyzing({})
    setAnalyzedVideos({})
    setAnalyzeErrors({})
    setView('search')
    localStorage.removeItem('yt-search-state')
  }

  const handleSearch = async (e?: FormEvent) => {
    e?.preventDefault()
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
        }),
      })

      const rawText = await res.text()
      if (!rawText) throw new Error(`Backend returned empty response (HTTP ${res.status})`)

      let data
      try { data = JSON.parse(rawText) } catch {
        throw new Error(`Backend returned non-JSON (HTTP ${res.status}): ${rawText.slice(0, 200)}`)
      }
      if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`)
      if (data.status === 'success') setSearchResults(data)
      else alert('Error: ' + data.detail)
    } catch (err) {
      alert('Error: ' + (err as Error).message)
    }
    setLoadingSearch(false)
  }

  const handleAnalyze = async (videoId: string, title: string) => {
    if (analyzing[videoId] === 'loading') return
    setAnalyzing((prev) => ({ ...prev, [videoId]: 'loading' }))
    setAnalyzeErrors((prev) => { const n = { ...prev }; delete n[videoId]; return n })
    try {
      const res = await fetch(`${API_BASE}/analyze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ video_id: videoId, title, lang }),
      })
      const data = await res.json()
      if (data.status === 'success') {
        setAnalyzing((prev) => ({ ...prev, [videoId]: 'success' }))
        setAnalyzedVideos((prev) => ({
          ...prev,
          [videoId]: {
            filename: data.filename,
            collection_name: data.collection_name,
            title: data.title || title,
            chunks_count: data.chunks_count,
          },
        }))
        setSelectedFilename(data.filename)
        setChatVideoTitle(data.title || title)
        setChatHistory({})
        setView('chat')
        fetchDatasets()
      } else {
        setAnalyzing((prev) => ({ ...prev, [videoId]: 'error' }))
        setAnalyzeErrors((prev) => ({ ...prev, [videoId]: { type: data.transcript_status || 'failed_ytdlp', detail: data.detail || 'Unknown error' } }))
      }
    } catch (err) {
      setAnalyzing((prev) => ({ ...prev, [videoId]: 'error' }))
      setAnalyzeErrors((prev) => ({ ...prev, [videoId]: { type: 'failed_ytdlp', detail: (err as Error).message } }))
    }
  }

  const handleChat = async (e?: FormEvent) => {
    e?.preventDefault()
    if (!draft.trim() || !selectedFilename) return
    const question = draft.trim()
    const current = chatHistory[selectedFilename] || []
    const newChat = [...current, { role: 'user' as const, text: question }]
    setChatHistory((prev) => ({ ...prev, [selectedFilename]: newChat }))
    setDraft('')
    setLoadingChat(true)

    const match = Object.entries(analyzedVideos).find(([, v]) => v.filename === selectedFilename)
    const body: Record<string, any> = { query: question, filename: selectedFilename }
    if (match && match[1].collection_name) body.collection_name = match[1].collection_name

    try {
      const res = await fetch(`${API_BASE}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const data = await res.json()
      setChatHistory((prev) => ({ ...prev, [selectedFilename]: [...newChat, { role: 'assistant', text: data.answer, sources: data.sources }] }))
    } catch (err) {
      setChatHistory((prev) => ({ ...prev, [selectedFilename]: [...newChat, { role: 'assistant', text: 'Error: ' + (err as Error).message }] }))
    }
    setLoadingChat(false)
  }

  const selectAnalyzedVideo = (dataset: any) => {
    if (dataset.filename === selectedFilename && view === 'chat') {
      setView('search')
      return
    }
    const match = Object.entries(analyzedVideos).find(([, v]) => v.filename === dataset.filename)
    setSelectedFilename(dataset.filename)
    setChatVideoTitle(match ? match[1].title : dataset.name)
    setView('chat')
  }

  const gotoSearch = () => {
    localStorage.removeItem('yt-search-state')
    setView('search')
  }

  const tone = (id: string) => {
    const h = (id ?? '').charCodeAt(0)
    return h % 3 === 0 ? 'violet' : h % 3 === 1 ? 'blue' : 'amber'
  }

  const activeMessages = selectedFilename ? chatHistory[selectedFilename] || [] : []

  // Sidebar chat list = backend datasets merged with the persisted analyzed
  // videos, so previously-analyzed videos always appear as chats even before the
  // backend list loads (or if its file is missing).
  const chatList = (() => {
    const map = new Map<string, { filename: string; name: string; collection_name: string }>()
    for (const d of datasets) {
      const entry = Object.values(analyzedVideos).find((v) => v?.filename === d.filename)
      map.set(d.filename, { filename: d.filename, name: d.name, collection_name: entry?.collection_name || '' })
    }
    for (const v of Object.values(analyzedVideos)) {
      if (v?.filename && !map.has(v.filename)) {
        map.set(v.filename, { filename: v.filename, name: v.title || v.filename, collection_name: v.collection_name || '' })
      }
    }
    return [...map.values()]
  })()

  return (
    <div className={view === 'chat' ? 'chat-shell' : 'console-shell'}>
      {/* ===== Shared sidebar ===== */}
      <aside className="sidebar chat-sidebar">
        <div className="brand">
          <div className="brand-mark"><Play size={18} fill="currentColor" /></div>
          <div><strong>YT Deep Search</strong><span>VIDEO INTELLIGENCE</span></div>
        </div>

        <button className="new-search" onClick={gotoSearch}><Plus size={17} /> New search</button>

        <nav className="nav-list" aria-label="Main navigation">
          <p className="eyebrow">Workspace</p>
          <a className={`nav-item ${view === 'search' ? 'active' : ''}`} href="#search" onClick={(e) => { e.preventDefault(); setView('search') }}>
            <Search size={17} /> Search
          </a>
          <a className={`nav-item ${view === 'chat' ? 'active' : ''}`} href="#chat" onClick={(e) => { e.preventDefault(); setView('chat') }}>
            <MessageSquare size={17} /> Chats <span>{chatList.length}</span>
          </a>
          <a className="nav-item" href="#settings" onClick={(e) => e.preventDefault()}>
            <Settings2 size={17} /> Settings
          </a>
        </nav>

        <div className="library-label">
          <span className="eyebrow">Analyzed video</span>
          <div className="dataset-list">
            {chatList.length === 0 && <p className="empty-note">No video analyzed yet.</p>}
            {chatList.map((v) => (
              <div
                key={v.filename}
                className={`selected-video ${selectedFilename === v.filename ? 'active' : ''}`}
                onClick={() => selectAnalyzedVideo(v)}
              >
                <FileVideo size={15} />
                <span title={v.name}>{v.name}</span>
                {selectedFilename === v.filename && <Check size={14} />}
                <button className="dataset-delete" title="Delete" onClick={(e) => handleDelete(v.filename, e)}>
                  <Trash2 size={13} />
                </button>
              </div>
            ))}
          </div>
        </div>

        <div className="sidebar-foot"><span className="status-dot" /> Indexing service online</div>
      </aside>

      {/* ===== Search console ===== */}
      {view === 'search' && (
        <div className="content">
          <header className="topbar">
            <div>
              <span className="kicker">Video search</span>
              <h1>Find videos worth your time</h1>
            </div>
            <button className="icon-button" aria-label="Search settings"><Settings2 size={18} /></button>
          </header>

          <form className="search-panel" onSubmit={handleSearch}>
            <label>
              Search YouTube
              <div className="search-input">
                <Search size={16} />
                <input
                  value={keyword}
                  onChange={(e) => setKeyword(e.target.value)}
                  placeholder="Enter topic to research..."
                  required
                />
                <kbd>Enter</kbd>
              </div>
            </label>

            <div className="filters">
              <label>
                Language
                <select className="select-control" value={lang} onChange={(e) => setLang(e.target.value)}>
                  <option value="en">English (en)</option>
                  <option value="es">Spanish (es)</option>
                  <option value="ru">Russian (ru)</option>
                </select>
              </label>
              <label>
                Max videos
                <input type="number" className="control" min={1} max={100} value={maxVideos} onChange={(e) => setMaxVideos(e.target.value)} />
              </label>
              <label>
                Published after
                <input type="date" className="control" value={publishedAfter} onChange={(e) => setPublishedAfter(e.target.value)} />
              </label>
              <label>
                Published before
                <input type="date" className="control" value={publishedBefore} onChange={(e) => setPublishedBefore(e.target.value)} />
              </label>
            </div>

            <div className="actions">
              <button className="primary-button" type="submit" disabled={loadingSearch}>
                {loadingSearch ? <Loader2 size={15} className="spin" /> : <Search size={15} />}
                {loadingSearch ? 'Searching…' : 'Search'}
              </button>
              <button className="ghost-button" type="button" onClick={handleClearSearch}>Clear</button>
            </div>
          </form>

          {searchResults && !loadingSearch && (
            <div className="results-section">
              <div className="results-heading">
                <div className="result-title">
                  <h2>Results</h2>
                  <span className="result-count">{searchResults.videos_found} found</span>
                </div>
                <p>Click <strong>Analyze</strong> on a video to download & index its transcript.</p>
              </div>

              <div className="video-grid">
                {searchResults.video_details.map((v: any) => {
                  const vid = v.video_id
                  const isAnalyzed = analyzedVideos[vid]
                  const isAnalyzing = analyzing[vid] === 'loading'
                  const isError = analyzing[vid] === 'error'

                  return (
                    <div className="video-card" key={vid}>
                      {v.thumbnail_url ? (
                        <div className={`thumbnail ${tone(vid)}`}>
                          <img src={v.thumbnail_url} alt="" loading="lazy" />
                          <span>{v.published_date?.slice(0, 10)}</span>
                        </div>
                      ) : (
                        <div className={`thumbnail ${tone(vid)}`}>
                          <Play size={22} fill="currentColor" />
                          <span>{v.published_date?.slice(0, 10)}</span>
                        </div>
                      )}

                      <div className="video-info">
                        <div className="video-meta">
                          {isAnalyzed ? (
                            <span className="status"><Check size={12} /> Analyzed</span>
                          ) : isAnalyzing ? (
                            <span className="status indexing"><Loader2 size={12} className="spin" /> Indexing</span>
                          ) : isError ? (
                            <span className="status error">Failed</span>
                          ) : (
                            <span className="status">Not analyzed</span>
                          )}
                          <span>{v.published_date?.slice(0, 10)}</span>
                        </div>

                        <h3>
                          <a href={`https://www.youtube.com/watch?v=${vid}`} target="_blank" rel="noreferrer" title={v.title || vid}>
                            {v.title || vid}
                          </a>
                        </h3>
                        <p>{isError && analyzeErrors[vid] ? analyzeErrors[vid].detail : `Video ID ${vid}`}</p>

                        {isAnalyzed ? (
                          <button className="analyze-button" onClick={() => { setSelectedFilename(isAnalyzed.filename); setChatVideoTitle(isAnalyzed.title); setChatHistory({}); setView('chat') }}>
                            <MessageSquare size={13} /> Chat
                          </button>
                        ) : isError ? (
                          <button className="analyze-button" onClick={() => handleAnalyze(vid, v.title)}>
                            <Sparkles size={13} /> {analyzeErrors[vid]?.type === 'no_transcript' ? 'Analyze' : 'Retry'}
                          </button>
                        ) : (
                          <button className="analyze-button" onClick={() => handleAnalyze(vid, v.title)} disabled={isAnalyzing}>
                            <Play size={13} /> {isAnalyzing ? 'Indexing…' : 'Analyze'}
                          </button>
                        )}
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          )}
        </div>
      )}

      {/* ===== Chat view ===== */}
      {view === 'chat' && (
        <section className="chat-content" id="chat">
          <header className="chat-header">
            <div className="chat-heading">
              <a className="back-link" href="#search" onClick={(e) => { e.preventDefault(); setView('search') }}><ArrowLeft size={16} /> Back</a>
              <div>
                <span className="kicker">Video chat</span>
                <h1>{chatVideoTitle || selectedFilename.replace('_chunked.jsonl', '') || 'Select a video'}</h1>
              </div>
            </div>
            <button className="icon-button" aria-label="Chat settings"><Settings2 size={18} /></button>
          </header>

          <div className="video-context">
            <div className="context-thumb"><Play size={19} fill="currentColor" /></div>
            <div>
              <strong>Transcript ready</strong>
              <span>Indexed {selectedFilename ? '· ' + (analyzedVideos[selectedFilename]?.chunks_count ?? '') + ' chunks' : ''}</span>
            </div>
            <button className="context-action">View transcript <ChevronDown size={15} /></button>
          </div>

          <div className="conversation">
            {activeMessages.length === 0 ? (
              <div className="empty-chat">
                <div className="spark-icon"><Sparkles size={20} /></div>
                <h2>Ask anything about this video</h2>
                <p>Explore the transcript with focused questions. Answers stay tied to what the creator actually said.</p>
                {suggestions.length > 0 && (
                  <div className="suggestion-list">
                    {suggestions.map((s) => (
                      <button key={s} onClick={() => setDraft(s)}>{s}<ArrowLeft size={14} /></button>
                    ))}
                  </div>
                )}
                {suggestLoading && <p className="suggest-hint"><Loader2 size={12} className="spin" /> Generating suggestions from this transcript…</p>}
              </div>
            ) : (
              <div className="message-list">
                {activeMessages.map((m, i) => (
                  <div className={`message-row ${m.role}`} key={i}>
                    <div className="message-label">{m.role === 'user' ? 'You' : 'Deep Search'}</div>
                    <div className="message-bubble">
                      {m.text}
                      {m.sources && m.sources.length > 0 && (
                        <div className="msg-sources">
                          <div className="msg-sources-label">Sources:</div>
                          {Array.from(new Set(m.sources.map((s) => s.video_id))).map((vid) => {
                            const source = m.sources!.find((s) => s.video_id === vid)
                            return (
                              <a key={vid} href={`https://www.youtube.com/watch?v=${vid}`} target="_blank" rel="noreferrer" className="video-link">
                                <span className="play">▶</span> {source?.title || `Video ${vid}`}
                              </a>
                            )
                          })}
                        </div>
                      )}
                    </div>
                  </div>
                ))}
                {loadingChat && (
                  <div className="message-row assistant">
                    <div className="message-label">Deep Search</div>
                    <div className="message-bubble"><Loader2 size={14} className="spin" /> Thinking…</div>
                  </div>
                )}
              </div>
            )}
          </div>

          <form className="composer" onSubmit={handleChat}>
            <button type="button" className="attach-button" aria-label="Attach context"><Paperclip size={18} /></button>
            <input
              aria-label="Ask a question"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder={selectedFilename ? 'Ask a question about this video...' : 'Select a video first...'}
              disabled={loadingChat || !selectedFilename}
            />
            <button className="send-button" type="submit" aria-label="Send question" disabled={loadingChat || !selectedFilename}>
              <Send size={17} />
            </button>
          </form>
          <p className="composer-hint">Answers are generated from the indexed transcript · Press Enter to send</p>
        </section>
      )}
    </div>
  )
}
