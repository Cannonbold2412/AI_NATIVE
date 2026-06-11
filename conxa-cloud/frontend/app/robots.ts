import type { MetadataRoute } from 'next'
import { SITE_ORIGIN, absoluteUrl } from '@/lib/siteMetadata'

export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: '*',
      allow: ['/', '/docs', '/docs/'],
      disallow: [
        '/api/',
        '/billing',
        '/dashboard',
        '/plugins',
        '/packages',
        '/compile',
        '/build-installer',
        '/plugin-health',
        '/settings',
        '/team',
        '/test',
      ],
    },
    sitemap: absoluteUrl('/sitemap.xml'),
    host: SITE_ORIGIN,
  }
}
