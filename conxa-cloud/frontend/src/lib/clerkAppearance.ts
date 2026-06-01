import { dark } from '@clerk/ui/themes'

export const clerkAppearance = {
  theme: dark,
  variables: {
    borderRadius: '0.625rem',
    colorBackground: '#111318',
    colorBorder: 'rgba(255, 255, 255, 0.1)',
    colorDanger: '#ef4444',
    colorForeground: '#f4f4f5',
    colorInput: '#181b20',
    colorInputForeground: '#f4f4f5',
    colorModalBackdrop: 'rgba(3, 7, 18, 0.82)',
    colorMuted: '#181b20',
    colorMutedForeground: '#a1a1aa',
    colorNeutral: 'white',
    colorPrimary: '#f4f4f5',
    colorPrimaryForeground: '#09090b',
    colorRing: 'rgba(244, 244, 245, 0.35)',
    colorShadow: '#000000',
    fontFamily: 'Geist Variable, sans-serif',
    fontFamilyButtons: 'Geist Variable, sans-serif',
  },
  elements: {
    card: 'bg-[#111318] text-zinc-100',
    cardBox: 'border border-white/10 bg-[#111318] shadow-2xl shadow-black/30',
    dividerLine: 'bg-white/10',
    dividerText: 'text-zinc-500',
    footerActionLink: 'text-zinc-50 hover:text-zinc-300',
    footerActionText: 'text-zinc-400',
    formButtonPrimary:
      'bg-zinc-100 text-zinc-950 hover:bg-white disabled:bg-zinc-700 disabled:text-zinc-300',
    formFieldInput:
      'border-white/10 bg-[#181b20] text-zinc-100 caret-zinc-100 placeholder:text-zinc-500 focus:border-white/30 focus:ring-white/20',
    formFieldLabel: 'text-zinc-200',
    headerSubtitle: 'text-zinc-400',
    headerTitle: 'text-zinc-50',
    identityPreviewText: 'text-zinc-100',
    organizationPreviewMainIdentifier: 'text-zinc-100',
    organizationPreviewSecondaryIdentifier: 'text-zinc-400',
    rootBox: 'text-zinc-100',
    socialButtonsBlockButton:
      'border-white/10 bg-[#181b20] text-zinc-100 hover:bg-[#20242b]',
    socialButtonsBlockButtonText: 'text-zinc-100',
  },
}
