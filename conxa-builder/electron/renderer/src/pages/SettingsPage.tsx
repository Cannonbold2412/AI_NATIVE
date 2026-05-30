import { useAuth } from '@/contexts/AuthContext'
import { PageHeader } from '@/components/layout/PageHeader'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { performLogout } from '@/contexts/AuthContext'
import { LogOut } from 'lucide-react'

export function SettingsPage() {
  const { identity, setIdentity } = useAuth()

  return (
    <div className="h-full overflow-y-auto">
      <PageHeader title="Settings" description="Account and workspace settings for Conxa Build Studio." />
      <div className="mx-auto grid w-full max-w-4xl gap-4 px-4 py-4 sm:px-6">
        <Card className="border-white/8 bg-white/[0.03] shadow-none">
          <CardHeader className="border-b border-white/8">
            <CardTitle className="text-white">Account</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 p-4">
            {identity ? (
              <>
                <div className="rounded-lg border border-white/8 bg-black/20 p-3">
                  <p className="text-xs uppercase tracking-[0.16em] text-zinc-500">Email</p>
                  <p className="mt-1 text-sm text-white">{identity.email}</p>
                </div>
                {identity.name && (
                  <div className="rounded-lg border border-white/8 bg-black/20 p-3">
                    <p className="text-xs uppercase tracking-[0.16em] text-zinc-500">Name</p>
                    <p className="mt-1 text-sm text-white">{identity.name}</p>
                  </div>
                )}
                {identity.org_name && (
                  <div className="rounded-lg border border-white/8 bg-black/20 p-3">
                    <p className="text-xs uppercase tracking-[0.16em] text-zinc-500">Organisation</p>
                    <p className="mt-1 text-sm text-white">{identity.org_name}</p>
                  </div>
                )}
                <Button
                  variant="outline"
                  size="sm"
                  className="gap-2 border-white/10 text-zinc-300 hover:text-white"
                  onClick={() => performLogout(setIdentity)}
                >
                  <LogOut className="size-4" />
                  Sign out
                </Button>
              </>
            ) : (
              <p className="text-sm text-zinc-500">Not signed in.</p>
            )}
          </CardContent>
        </Card>

        <Card className="border-white/8 bg-white/[0.03] shadow-none">
          <CardHeader className="border-b border-white/8">
            <CardTitle className="text-white">About</CardTitle>
          </CardHeader>
          <CardContent className="p-4">
            <div className="rounded-lg border border-white/8 bg-black/20 p-3">
              <p className="text-xs uppercase tracking-[0.16em] text-zinc-500">Product</p>
              <p className="mt-1 text-sm text-white">Conxa Build Studio</p>
              <p className="mt-0.5 text-xs text-zinc-500">Offline AI-native workflow recorder & compiler</p>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
