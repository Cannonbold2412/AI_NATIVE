import type { Metadata } from 'next'
import { DocsIndex } from '@/components/marketing/docs/PublicDocs'

export const metadata: Metadata = {
  title: 'Docs | CONXA',
  description:
    'Public CONXA documentation for product behavior, security, privacy, terms, billing, and support.',
}

export default function PublicDocsIndexPage() {
  return <DocsIndex />
}
