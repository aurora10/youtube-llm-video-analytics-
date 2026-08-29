import { NextRequest, NextResponse } from 'next/server'

// FastAPI backend (see api.py). Long-running calls (e.g. /api/analyze, which runs
// up to 7 yt-dlp attempts) can take ~45-60s. Next.js rewrites proxy with a hard
// 30s timeout, so we route /api through this handler with a generous timeout
// instead.
const BACKEND = process.env.BACKEND_URL || 'http://127.0.0.1:8000'
const TIMEOUT_MS = 10 * 60 * 1000 // 10 minutes

export const dynamic = 'force-dynamic'

async function proxy(req: NextRequest, segments: string[]) {
  const url = `${BACKEND}/api/${segments.map(encodeURIComponent).join('/')}${req.nextUrl.search}`
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS)

  try {
    const hasBody = req.method === 'POST' || req.method === 'PUT' || req.method === 'PATCH'
    const body = hasBody ? await req.text() : undefined

    const upstream = await fetch(url, {
      method: req.method,
      body,
      headers: body
        ? { 'content-type': req.headers.get('content-type') || 'application/json' }
        : undefined,
      redirect: 'manual',
      signal: controller.signal,
    })

    const text = await upstream.text()
    return new NextResponse(text, {
      status: upstream.status,
      headers: {
        'content-type': upstream.headers.get('content-type') || 'application/json',
      },
    })
  } catch (err) {
    console.error('[api proxy]', err)
    return NextResponse.json(
      { detail: err instanceof Error ? err.message : 'Backend unreachable' },
      { status: 502 },
    )
  } finally {
    clearTimeout(timer)
  }
}

type Ctx = { params: Promise<{ path: string[] }> }

export async function GET(req: NextRequest, ctx: Ctx) {
  const { path } = await ctx.params
  return proxy(req, path)
}

export async function POST(req: NextRequest, ctx: Ctx) {
  const { path } = await ctx.params
  return proxy(req, path)
}

export async function DELETE(req: NextRequest, ctx: Ctx) {
  const { path } = await ctx.params
  return proxy(req, path)
}

export async function PUT(req: NextRequest, ctx: Ctx) {
  const { path } = await ctx.params
  return proxy(req, path)
}
