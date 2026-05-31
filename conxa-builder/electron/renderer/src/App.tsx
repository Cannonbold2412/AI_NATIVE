import { useEffect, useState } from 'react'
import { Routes, Route, Navigate, useNavigate } from 'react-router-dom'
import { cmd } from '@/lib/ipc'
import { AuthContext, performLogout, type Identity } from '@/contexts/AuthContext'
import { AppChrome } from '@/components/layout/AppChrome'
import { LoginOverlay } from '@/components/LoginOverlay'
import { ErrorBoundary } from '@/components/ErrorBoundary'

// Pages
import { DashboardPage } from '@/pages/DashboardPage'
import { PluginsPage } from '@/pages/PluginsPage'
import { PluginDetailPage } from '@/pages/PluginDetailPage'
import { HumanEditPage } from '@/pages/HumanEditPage'
import { BuildPage } from '@/pages/BuildPage'
import { BuildInstallerPage } from '@/pages/BuildInstallerPage'
import { TestPluginPage } from '@/pages/TestPluginPage'
import { SkillPackagesPage } from '@/pages/SkillPackagesPage'
import { SettingsPage } from '@/pages/SettingsPage'

// Studio-exclusive pages (keep existing)
import { RecordingFeed } from '@/pages/RecordingFeed'
import { CompileProgress } from '@/pages/CompileProgress'
import { CompilePage } from '@/pages/CompilePage'

function SplashScreen() {
  return (
    <div className="flex h-dvh items-center justify-center bg-[#090b0d]">
      <div className="size-8 animate-pulse rounded-full bg-white/10" />
    </div>
  )
}

function DeepLinkHandler() {
  const navigate = useNavigate()
  useEffect(() => {
    return window.conxa.onDeepLink((url) => {
      const pluginMatch = url.match(/[?&]plugin=([^&]+)/)
      const pluginId = pluginMatch ? decodeURIComponent(pluginMatch[1]) : null
      navigate(pluginId ? `/plugins/${pluginId}` : '/dashboard')
    })
  }, [navigate])
  return null
}

export function App() {
  const [identity, setIdentity] = useState<Identity | null | 'checking'>('checking')

  useEffect(() => {
    cmd<{ identity: Identity | null }>('whoami')
      .then((r) => setIdentity(r?.identity ?? null))
      .catch(() => setIdentity(null))
  }, [])

  if (identity === 'checking') return <SplashScreen />

  const resolvedIdentity = identity as Identity | null

  const logout = () => performLogout(setIdentity)

  return (
    <AuthContext.Provider value={{ identity: resolvedIdentity, setIdentity, logout }}>
      <ErrorBoundary>
        <AppChrome>
          <DeepLinkHandler />
          <Routes>
            <Route path="/" element={<Navigate to="/dashboard" replace />} />
            <Route path="/dashboard" element={<DashboardPage />} />
            <Route path="/plugins" element={<PluginsPage />} />
            <Route path="/plugins/:pluginId" element={<PluginDetailPage />} />
            <Route path="/plugins/:pluginId/record/:workflowName" element={<RecordingFeed />} />
            <Route path="/plugins/:pluginId/compile/:sessionId" element={<CompileProgress />} />
            <Route path="/compile" element={<CompilePage />} />
            <Route path="/edit" element={<HumanEditPage />} />
            <Route path="/edit/:skillId" element={<HumanEditPage />} />
            <Route path="/build" element={<BuildPage />} />
            <Route path="/test" element={<TestPluginPage />} />
            <Route path="/build-installer" element={<BuildInstallerPage />} />
            <Route path="/packages" element={<SkillPackagesPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="*" element={<Navigate to="/dashboard" replace />} />
          </Routes>
        </AppChrome>
      </ErrorBoundary>
      {!resolvedIdentity && <LoginOverlay onLogin={setIdentity} />}
    </AuthContext.Provider>
  )
}
