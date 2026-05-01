import { Route, Routes } from 'react-router-dom'
import { HomePage } from './HomePage'
import { HumanEditPage } from './HumanEditPage'
import { SkillPackBuilderPage } from './SkillPackBuilderPage'
import { SkillJsonPage } from './SkillJsonPage'
import { SkillLibraryPage } from './SkillLibraryPage'
import { SkillPackagesPage } from './SkillPackagesPage'

function App() {
  return (
    <Routes>
      <Route path="/" element={<HomePage />} />
      <Route path="/edit" element={<HumanEditPage />} />
      <Route path="/edit/:skillId" element={<HumanEditPage />} />
      <Route path="/skills/:skillId/json" element={<SkillJsonPage />} />
      <Route path="/package" element={<SkillPackagesPage />} />
      <Route path="/packages" element={<SkillPackagesPage />} />
      <Route path="/skill-pack-builder" element={<SkillPackBuilderPage />} />
      <Route path="/skills" element={<SkillLibraryPage mode="skills" />} />
    </Routes>
  )
}

export default App
