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

const INTERNAL_PROXY_HEADERS = new Set([
  'x-conxa-proxy-secret',
  'x-conxa-user-id',
  'x-conxa-org-id',
  'x-conxa-org-role',
  'x-conxa-org-name',
])

function upstreamOrigin() {
  return (process.env.API_ORIGIN || '').replace(/\/$/, '')
}

function apiProxySecret() {
  return (process.env.CONXA_API_PROXY_SECRET || '').trim()
}

let warnedMissingProxySecret = false
let warnedMissingOrgId = false

async function proxy(request: Request, path: string[]) {
  const origin = upstreamOrigin()
  if (!origin) {
    return Response.json({ detail: 'api_origin_not_configured' }, { status: 500 })
  }

  const { getToken, userId, orgId, orgRole, orgSlug } = await auth()
  const upstreamUrl = new URL(`${origin}/api/v1/${path.join('/')}`)
  const currentUrl = new URL(request.url)
  upstreamUrl.search = currentUrl.search

  const headers = new Headers()
  request.headers.forEach((value, key) => {
    const lower = key.toLowerCase()
    if (!HOP_BY_HOP_HEADERS.has(lower) && !INTERNAL_PROXY_HEADERS.has(lower)) {
      headers.set(key, value)
    }
  })
  headers.set('x-forwarded-host', currentUrl.host)

  const token = await getToken()
  if (token) {
    headers.set('authorization', `Bearer ${token}`)
  }
  const proxySecret = apiProxySecret()
  if (proxySecret && userId) {
    headers.set('x-conxa-proxy-secret', proxySecret)
    headers.set('x-conxa-user-id', userId)
    if (orgId) headers.set('x-conxa-org-id', orgId)
    if (orgRole) headers.set('x-conxa-org-role', orgRole)
    if (orgSlug) headers.set('x-conxa-org-name', orgSlug)
    if (!orgId && !warnedMissingOrgId) {
      warnedMissingOrgId = true
      console.warn('CONXA_API_PROXY_SECRET is configured, but Clerk did not provide an active orgId; backend will use the personal workspace.', {
        path: upstreamUrl.pathname,
      })
    }
  } else if (userId && !proxySecret && !warnedMissingProxySecret) {
    warnedMissingProxySecret = true
    console.warn('CONXA_API_PROXY_SECRET is not configured; backend workspace identity may fall back to Clerk JWT claims.', {
      path: upstreamUrl.pathname,
      hasOrgId: Boolean(orgId),
    })
  }

  const method = request.method.toUpperCase()
  const body =
    method === 'GET' || method === 'HEAD' ? undefined : await request.text()

  let upstream: Response
  try {
    upstream = await fetch(upstreamUrl, {
      method,
      headers,
      body,
    })
  } catch (error) {
    console.error('API proxy request failed', {
      origin,
      path: path.join('/'),
      error,
    })
    return Response.json(
      {
        detail: 'backend_unavailable',
        origin,
      },
      { status: 503 },
    )
  }

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
