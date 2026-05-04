import { auth } from '@clerk/nextjs/server'

const HOP_BY_HOP_HEADERS = new Set([
  'connection',
  'content-encoding',
  'content-length',
  'host',
  'keep-alive',
  'proxy-authenticate',
  'proxy-authorization',
  'te',
  'trailer',
  'transfer-encoding',
  'upgrade',
])

function upstreamOrigin() {
  return (process.env.API_ORIGIN || '').replace(/\/$/, '')
}

async function proxy(request: Request, path: string[]) {
  const origin = upstreamOrigin()
  if (!origin) {
    return Response.json({ detail: 'api_origin_not_configured' }, { status: 500 })
  }

  const { getToken } = await auth()
  const upstreamUrl = new URL(`${origin}/api/v1/${path.join('/')}`)
  const currentUrl = new URL(request.url)
  upstreamUrl.search = currentUrl.search

  const headers = new Headers()
  request.headers.forEach((value, key) => {
    if (!HOP_BY_HOP_HEADERS.has(key.toLowerCase())) {
      headers.set(key, value)
    }
  })
  headers.set('x-forwarded-host', currentUrl.host)

  const token = await getToken()
  if (token) {
    headers.set('authorization', `Bearer ${token}`)
  }

  const method = request.method.toUpperCase()
  const body =
    method === 'GET' || method === 'HEAD' ? undefined : await request.text()

  const upstream = await fetch(upstreamUrl, {
    method,
    headers,
    body,
  })

  const responseHeaders = new Headers()
  upstream.headers.forEach((value, key) => {
    if (!HOP_BY_HOP_HEADERS.has(key.toLowerCase())) {
      responseHeaders.set(key, value)
    }
  })

  return new Response(upstream.body, {
    status: upstream.status,
    headers: responseHeaders,
  })
}

type RouteContext = {
  params: Promise<{
    path: string[]
  }>
}

export async function GET(request: Request, context: RouteContext) {
  const { path } = await context.params
  return proxy(request, path)
}

export async function POST(request: Request, context: RouteContext) {
  const { path } = await context.params
  return proxy(request, path)
}

export async function PUT(request: Request, context: RouteContext) {
  const { path } = await context.params
  return proxy(request, path)
}

export async function PATCH(request: Request, context: RouteContext) {
  const { path } = await context.params
  return proxy(request, path)
}

export async function DELETE(request: Request, context: RouteContext) {
  const { path } = await context.params
  return proxy(request, path)
}
