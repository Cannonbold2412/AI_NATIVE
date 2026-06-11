import type { Metadata } from 'next'

export const SITE_NAME = 'CONXA'
export const SITE_ORIGIN = 'https://www.conxa.in'
export const SITE_METADATA_BASE = new URL(SITE_ORIGIN)

export const publicRobots = {
  index: true,
  follow: true,
  googleBot: {
    index: true,
    follow: true,
    'max-video-preview': -1,
    'max-image-preview': 'large',
    'max-snippet': -1,
  },
} satisfies Metadata['robots']

export const sitePublisher = {
  '@type': 'Organization',
  name: SITE_NAME,
  url: SITE_ORIGIN,
  logo: `${SITE_ORIGIN}/conxa-icon.png`,
}

export function absoluteUrl(path: string) {
  return new URL(path, SITE_ORIGIN).toString()
}

type PublicPageMetadataInput = {
  title: string
  description: string
  path: string
  type?: 'website' | 'article'
}

export function createPublicPageMetadata({
  title,
  description,
  path,
  type = 'website',
}: PublicPageMetadataInput): Metadata {
  const url = absoluteUrl(path)
  const image = absoluteUrl('/conxa-icon.png')

  return {
    title,
    description,
    alternates: {
      canonical: url,
    },
    robots: publicRobots,
    openGraph: {
      title,
      description,
      url,
      siteName: SITE_NAME,
      type,
      images: [
        {
          url: image,
          alt: SITE_NAME,
        },
      ],
    },
    twitter: {
      card: 'summary',
      title,
      description,
      images: [image],
    },
  }
}
