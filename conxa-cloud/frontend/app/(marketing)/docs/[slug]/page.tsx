import type { Metadata } from 'next'
import { notFound } from 'next/navigation'
import { DocsPage } from '@/components/marketing/docs/PublicDocs'
import { getPublicDoc, publicDocSlugs } from '@/content/publicDocs'

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
    return {
      title: 'Docs | CONXA',
    }
  }

  return {
    title: `${doc.title} | CONXA Docs`,
    description: doc.description,
  }
}

export default async function PublicDocPage({ params }: PageProps) {
  const { slug } = await params
  const doc = getPublicDoc(slug)

  if (!doc) {
    notFound()
  }

  return <DocsPage doc={doc} />
}
