import { SectionHeader } from '../primitives/SectionHeader'
import { Reveal } from '../primitives/Reveal'

const USE_CASES = [
  {
    tag: 'Government',
    headline: 'Automate government portal operations.',
    items: [
      'Procurement approvals and supplier onboarding',
      'License and permit applications',
      'Budget reconciliation across agencies',
      'HR processes in legacy government systems',
      'Compliance reporting and data entry',
    ],
    accent: '#22d3ee',
  },
  {
    tag: 'SaaS Internal Ops',
    headline: 'Operate your internal SaaS stack autonomously.',
    items: [
      'Employee onboarding across HR, access, and payroll tools',
      'Support ticket routing and CRM updates',
      'Finance reconciliation in NetSuite or SAP',
      'Deployment coordination in CI/CD dashboards',
      'Cross-platform data synchronization',
    ],
    accent: '#5eead4',
  },
]

export function GovSaas() {
  return (
    <section className="relative bg-[#0b0f14] px-6 py-28">
      <div className="mx-auto max-w-6xl">
        <SectionHeader
          eyebrow="Use cases"
          headline="Operational intelligence for every workflow."
          sub="From government portals to SaaS internal tools — CONXA executes anywhere a human can navigate a browser."
        />

        <div className="mt-16 grid gap-6 lg:grid-cols-2">
          {USE_CASES.map((uc, i) => (
            <Reveal key={uc.tag} delay={i * 0.1} direction={i === 0 ? 'left' : 'right'}>
              <div className="flex h-full flex-col rounded-2xl border border-white/6 bg-[#0f1620] p-8">
                <span
                  className="mb-4 inline-flex self-start rounded-full px-3 py-1 text-xs font-medium uppercase tracking-widest"
                  style={{ color: uc.accent, background: `${uc.accent}12`, border: `1px solid ${uc.accent}22` }}
                >
                  {uc.tag}
                </span>
                <h3 className="mb-6 text-xl font-semibold text-white">{uc.headline}</h3>
                <ul className="flex flex-col gap-3">
                  {uc.items.map((item) => (
                    <li key={item} className="flex items-start gap-3 text-sm text-[#9ba3af]">
                      <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: uc.accent }} />
                      {item}
                    </li>
                  ))}
                </ul>
              </div>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  )
}
