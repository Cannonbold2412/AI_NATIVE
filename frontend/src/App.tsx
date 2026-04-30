import { Route, Routes } from 'react-router-dom'
import { HomePage } from './HomePage'
import { HumanEditPage } from './HumanEditPage'
import { SkillJsonPage } from './SkillJsonPage'
import { SkillLibraryPage } from './SkillLibraryPage'

function App() {
  return (
    <Routes>
      <Route path="/" element={<HomePage />} />
      <Route path="/edit" element={<HumanEditPage />} />
      <Route path="/edit/:skillId" element={<HumanEditPage />} />
      <Route path="/skills/:skillId/json" element={<SkillJsonPage />} />
      <Route path="/packages" element={<SkillLibraryPage mode="packages" />} />
      <Route path="/skills" element={<SkillLibraryPage mode="skills" />} />
    </Routes>
  )
}

export default App
