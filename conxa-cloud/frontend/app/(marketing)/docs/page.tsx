import type { Metadata } from 'next'
import { DocsIndex } from '@/components/marketing/docs/PublicDocs'
import { createPublicPageMetadata } from '@/lib/siteMetadata'

export const metadata: Metadata = createPublicPageMetadata({
  title: 'Docs | CONXA',
  description:
    'Public CONXA documentation for Claude Desktop automation, MCP, local browser workflow execution, security, privacy, billing, and support.',
  path: '/docs',
})

export default function PublicDocsIndexPage() {
  return <DocsIndex />
}
