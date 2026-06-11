import type { Metadata } from 'next'
import { notFound } from 'next/navigation'
import { DocsPage } from '@/components/marketing/docs/PublicDocs'
import { getPublicDoc, publicDocSlugs } from '@/content/publicDocs'
import { createPublicPageMetadata } from '@/lib/siteMetadata'

type PageProps = {
  params: Promise<{
    slug: string
  }>
}

export const dynamicParams = false

export function generateStaticParams() {
  return publicDocSlugs.map((slug) => ({ slug }))
}

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { slug } = await params
  const doc = getPublicDoc(slug)

  if (!doc) {
    return createPublicPageMetadata({
      title: 'Docs | CONXA',
      description:
        'Public CONXA documentation for Claude Desktop automation, MCP, local execution, security, privacy, billing, and support.',
      path: '/docs',
    })
  }

  return createPublicPageMetadata({
    title: `${doc.title} | CONXA Docs`,
    description: doc.description,
    path: `/docs/${doc.slug}`,
    type: 'article',
  })
}

export default async function PublicDocPage({ params }: PageProps) {
  const { slug } = await params
  const doc = getPublicDoc(slug)

  if (!doc) {
    notFound()
  }

  return <DocsPage doc={doc} />
}
