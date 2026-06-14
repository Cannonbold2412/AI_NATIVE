import { useEffect } from 'react'
import { useAuth } from '@/contexts/AuthContext'
import { PageHeader } from '@/components/layout/PageHeader'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { performLogout } from '@/contexts/AuthContext'
import { LogOut, RefreshCw } from 'lucide-react'
import { EntitlementMeters } from '@/components/EntitlementMeters'
import { useUpdater } from '@/hooks/useUpdater'

function SoftwareUpdateCard() {
  const { status, currentVersion, check, startDownload, install } = useUpdater()

  useEffect(() => {
    if (status.phase === 'downloaded') install()
  }, [status.phase, install])

  const isChecking = status.phase === 'checking'
  const isAvailable = status.phase === 'available'
  const isNotAvailable = status.phase === 'not-available'
  const isDownloading = status.phase === 'downloading'
  const isDownloaded = status.phase === 'downloaded'
  const hasError = status.phase === 'error'

  return (
    <Card className="border-white/8 bg-white/[0.03] shadow-none">
      <CardHeader className="border-b border-white/8">
        <CardTitle className="text-white">Software Update</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 p-4">
        <div className="rounded-lg border border-white/8 bg-black/20 p-3">
          <p className="text-xs uppercase tracking-[0.16em] text-zinc-500">Current version</p>
          <p className="mt-1 text-sm text-white">{currentVersion || '—'}</p>
        </div>

        {isAvailable && status.phase === 'available' && (
          <div className="rounded-lg border border-white/8 bg-black/20 p-3">
            <p className="text-xs uppercase tracking-[0.16em] text-zinc-500">New version available</p>
            <p className="mt-1 text-sm text-white">{status.latestVersion}</p>
          </div>
        )}

        {isDownloading && status.phase === 'downloading' && (
          <div>
            <div className="mb-1 flex justify-between text-xs text-zinc-500">
              <span>Downloading update...</span>
              <span>{Math.round(status.percent)}%</span>
            </div>
            <div className="h-1.5 overflow-hidden rounded-full bg-white/5">
              <div
                className="h-full rounded-full bg-blue-500 transition-all duration-300"
                style={{ width: `${status.percent}%` }}
              />
            </div>
          </div>
        )}

        {isNotAvailable && (
          <p className="text-sm text-zinc-500">You're up to date.</p>
        )}

        {(isDownloaded) && (
          <p className="text-sm text-zinc-500">Installing and restarting...</p>
        )}

        {hasError && status.phase === 'error' && (
          <p className="text-xs text-red-400">{status.message}</p>
        )}

        <div className="flex gap-2">
          {!isDownloading && !isDownloaded && (
            <Button
              variant="outline"
              size="sm"
              className="gap-2 border-white/10 text-zinc-300 hover:text-white"
              onClick={check}
              disabled={isChecking}
            >
              <RefreshCw className={`size-4 ${isChecking ? 'animate-spin' : ''}`} />
              {isChecking ? 'Checking...' : 'Check for updates'}
            </Button>
          )}
          {(isAvailable || hasError) && (
            <Button
              size="sm"
              onClick={startDownload}
              disabled={isDownloading}
            >
              Update now
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  )
}

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
            <CardTitle className="text-white">Usage</CardTitle>
          </CardHeader>
          <CardContent className="p-4">
            <EntitlementMeters />
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

        <SoftwareUpdateCard />
      </div>
    </div>
  )
}
