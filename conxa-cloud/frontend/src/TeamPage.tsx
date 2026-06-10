'use client'

import { OrganizationProfile } from '@clerk/nextjs'
import { PageHeader } from '@/components/layout/PageHeader'
import { EntitlementMeters } from '@/components/EntitlementMeters'
import { clerkAppearance } from '@/lib/clerkAppearance'

export function TeamPage() {
  return (
    <div className="h-full overflow-y-auto">
      <PageHeader title="Team" description="Workspace membership and organization controls." />
      <div className="mx-auto flex w-full max-w-4xl flex-col gap-4 px-4 py-6 sm:px-6">
        <EntitlementMeters meters={['seats']} />
        <OrganizationProfile
          routing="hash"
          appearance={{
            ...clerkAppearance,
            elements: {
              ...clerkAppearance.elements,
              rootBox: 'w-full',
              card: 'bg-transparent border border-white/8 shadow-none',
              navbar: 'hidden',
              pageScrollBox: 'p-0',
            },
          }}
        />
      </div>
    </div>
  )
}
