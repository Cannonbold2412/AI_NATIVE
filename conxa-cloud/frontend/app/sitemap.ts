import type { MetadataRoute } from 'next'
import { publicDocs, PUBLIC_DOCS_LAST_MODIFIED } from '@/content/publicDocs'
import { absoluteUrl } from '@/lib/siteMetadata'

export default function sitemap(): MetadataRoute.Sitemap {
  const staticRoutes: MetadataRoute.Sitemap = [
    {
      url: absoluteUrl('/'),
      lastModified: PUBLIC_DOCS_LAST_MODIFIED,
      changeFrequency: 'weekly',
      priority: 1,
    },
    {
      url: absoluteUrl('/docs'),
      lastModified: PUBLIC_DOCS_LAST_MODIFIED,
      changeFrequency: 'weekly',
      priority: 0.9,
    },
  ]

  const docsRoutes = publicDocs.map((doc) => ({
    url: absoluteUrl(`/docs/${doc.slug}`),
    lastModified: PUBLIC_DOCS_LAST_MODIFIED,
    changeFrequency: 'monthly' as const,
    priority: doc.slug === 'claude-automation' ? 0.9 : 0.75,
  }))

  return [...staticRoutes, ...docsRoutes]
}
