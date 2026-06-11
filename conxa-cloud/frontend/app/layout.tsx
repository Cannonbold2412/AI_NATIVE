import type { Metadata } from 'next'
import { ClerkProvider } from '@clerk/nextjs'
import './globals.css'
import { AppProviders } from './providers'
import { clerkAppearance } from '@/lib/clerkAppearance'
import { SITE_METADATA_BASE, SITE_NAME, publicRobots } from '@/lib/siteMetadata'

export const metadata: Metadata = {
  metadataBase: SITE_METADATA_BASE,
  applicationName: SITE_NAME,
  title: SITE_NAME,
  description: 'AI operational runtime — operate software by talking.',
  robots: publicRobots,
  openGraph: {
    title: SITE_NAME,
    description: 'AI operational runtime — operate software by talking.',
    url: '/',
    siteName: SITE_NAME,
    type: 'website',
    images: [
      {
        url: '/conxa-icon.png',
        alt: SITE_NAME,
      },
    ],
  },
  twitter: {
    card: 'summary',
    title: SITE_NAME,
    description: 'AI operational runtime — operate software by talking.',
    images: ['/conxa-icon.png'],
  },
  icons: {
    icon: '/conxa-icon.png',
    shortcut: '/conxa-icon.png',
    apple: '/conxa-icon.png',
  },
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html lang="en" className="dark">
      <body>
        <ClerkProvider
          appearance={clerkAppearance}
          signInForceRedirectUrl="/dashboard"
          signUpForceRedirectUrl="/dashboard"
        >
          <AppProviders>
            {children}
          </AppProviders>
        </ClerkProvider>
      </body>
    </html>
  )
}
