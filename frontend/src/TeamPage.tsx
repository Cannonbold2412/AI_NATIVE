'use client'

import { OrganizationSwitcher } from '@clerk/nextjs'
import { AppShell } from '@/components/layout/AppLayout'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

export function TeamPage() {
  return (
    <AppShell title="Team" description="Workspace membership and organization controls." mainClassName="overflow-y-auto">
      <div className="mx-auto flex w-full max-w-4xl flex-col gap-4 px-4 py-4 sm:px-6">
        <Card className="border-white/8 bg-white/[0.03] shadow-none">
          <CardHeader className="border-b border-white/8">
            <CardTitle className="text-white">Members</CardTitle>
          </CardHeader>
          <CardContent className="p-4">
            <OrganizationSwitcher hidePersonal afterSelectOrganizationUrl="/" afterCreateOrganizationUrl="/" />
          </CardContent>
        </Card>
      </div>
    </AppShell>
  )
}
