import type { Metadata } from 'next'
import { ClerkProvider } from '@clerk/nextjs'
import './globals.css'
import { AppProviders } from './providers'

const clerkAppearance = {
  variables: {
    borderRadius: '0.625rem',
    colorBackground: '#111318',
    colorDanger: '#ef4444',
    colorInputBackground: '#181b20',
    colorInputText: '#f4f4f5',
    colorNeutral: '#111318',
    colorPrimary: '#f4f4f5',
    colorText: '#f4f4f5',
    colorTextSecondary: '#a1a1aa',
    fontFamily: 'Geist Variable, sans-serif',
  },
  elements: {
    card: 'bg-[#111318] text-white',
    cardBox: 'border border-white/10 bg-[#111318] shadow-2xl shadow-black/30',
    dividerLine: 'bg-white/10',
    dividerText: 'text-zinc-500',
    footerActionLink: 'text-white hover:text-zinc-300',
    footerActionText: 'text-zinc-400',
    formButtonPrimary: 'bg-white text-black hover:bg-zinc-200',
    formFieldInput:
      'border-white/10 bg-[#181b20] text-white placeholder:text-zinc-500 focus:border-white/30 focus:ring-white/20',
    formFieldLabel: 'text-zinc-200',
    headerSubtitle: 'text-zinc-400',
    headerTitle: 'text-white',
    socialButtonsBlockButton: 'border-white/10 bg-[#181b20] text-white hover:bg-[#20242b]',
  },
}

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
