import { lazy, Suspense } from 'react'
import { Route, Routes } from 'react-router-dom'

const HomePage = lazy(() => import('./HomePage').then((m) => ({ default: m.HomePage })))
const HumanEditPage = lazy(() => import('./HumanEditPage').then((m) => ({ default: m.HumanEditPage })))
const SkillPackBuilderPage = lazy(() =>
  import('./SkillPackBuilderPage').then((m) => ({ default: m.SkillPackBuilderPage })),
)
const SkillJsonPage = lazy(() => import('./SkillJsonPage').then((m) => ({ default: m.SkillJsonPage })))
const SkillLibraryPage = lazy(() =>
  import('./SkillLibraryPage').then((m) => ({ default: m.SkillLibraryPage })),
)
const SkillPackagesPage = lazy(() =>
  import('./SkillPackagesPage').then((m) => ({ default: m.SkillPackagesPage })),
)

function RouteFallback() {
  return (
    <div className="flex min-h-[50vh] items-center justify-center">
      <div className="h-8 w-8 animate-spin rounded-full border-2 border-zinc-500 border-t-transparent" aria-hidden />
      <span className="sr-only">Loading…</span>
    </div>
  )
}

function App() {
  return (
    <Suspense fallback={<RouteFallback />}>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/edit" element={<HumanEditPage />} />
        <Route path="/edit/:skillId" element={<HumanEditPage />} />
        <Route path="/skills/:skillId/json" element={<SkillJsonPage />} />
        <Route path="/pakage" element={<SkillPackagesPage />} />
        <Route path="/package" element={<SkillPackagesPage />} />
        <Route path="/packages" element={<SkillPackagesPage />} />
        <Route path="/skill-pack-builder" element={<SkillPackBuilderPage />} />
        <Route path="/skills" element={<SkillLibraryPage mode="skills" />} />
      </Routes>
    </Suspense>
  )
}

export default App
