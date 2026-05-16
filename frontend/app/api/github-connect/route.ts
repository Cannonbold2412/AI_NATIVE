import { NextResponse } from 'next/server'
import { auth } from '@clerk/nextjs/server'

export async function GET() {
  const origin = (process.env.API_ORIGIN || 'http://localhost:8000').replace(/\/$/, '')
  const { getToken } = await auth()
  const token = await getToken()
  const headers = new Headers()

  if (token) {
    headers.set('authorization', `Bearer ${token}`)
  }

  let upstream: Response
  try {
    upstream = await fetch(`${origin}/api/v1/integrations/github/connect`, {
      headers,
      redirect: 'manual',
    })
  } catch {
    return NextResponse.json({ detail: 'backend_unavailable', origin }, { status: 503 })
  }

  const location = upstream.headers.get('location')
  if (upstream.status >= 300 && upstream.status < 400 && location) {
    return NextResponse.redirect(location)
  }

  let detail = upstream.statusText || 'github_oauth_start_failed'
  try {
    const body = (await upstream.json()) as { detail?: unknown }
    if (typeof body.detail === 'string' && body.detail.trim()) {
      detail = body.detail.trim()
    }
  } catch {
    // keep status text
  }

  return NextResponse.json({ detail }, { status: upstream.status || 502 })
}
