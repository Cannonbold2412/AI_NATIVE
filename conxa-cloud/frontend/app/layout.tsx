import type { Metadata } from 'next'
import { ClerkProvider } from '@clerk/nextjs'
import './globals.css'
import { AppProviders } from './providers'
import { clerkAppearance } from '@/lib/clerkAppearance'

export const metadata: Metadata = {
  title: 'CONXA',
  description: 'AI operational runtime — operate software by talking.',
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
