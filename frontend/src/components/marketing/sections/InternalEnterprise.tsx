import { SectionHeader } from '../primitives/SectionHeader'
import { Reveal } from '../primitives/Reveal'

const FEATURES = [
  {
    icon: '🔒',
    title: 'No codebase exposure',
    desc: 'Workflows operate at the browser layer. No API keys, no SDK integrations, no platform source code required.',
  },
  {
    icon: '🏢',
    title: 'Private deployment',
    desc: 'Run CONXA runtime inside your own infrastructure. Your data stays on your machines.',
  },
  {
    icon: '📋',
    title: 'Full audit trail',
    desc: 'Every action logged with user, timestamp, step, and recovery event. SOC 2 compatible by design.',
  },
  {
    icon: '👥',
    title: 'Role-based execution',
    desc: 'Control which team members can trigger which workflows. Permissions enforced before execution starts.',
  },
  {
    icon: '🔑',
    title: 'Credential isolation',
    desc: 'CONXA holds no credentials in plaintext. Secrets are injected at runtime from your vault.',
  },
  {
    icon: '⚙️',
    title: 'Works on internal tools',
    desc: 'No public API required. If a human can open it in a browser, CONXA can operate it.',
  },
]

export function InternalEnterprise() {
  return (
    <section id="enterprise" className="relative bg-[#0b0f14] px-6 py-28">
      <div className="mx-auto max-w-6xl">
        <div className="grid gap-16 lg:grid-cols-[1fr_1fr] lg:items-center">
          {/* Text */}
          <div>
            <SectionHeader
              eyebrow="Enterprise & internal ops"
              headline="Operate behind your firewall."
              sub="CONXA is designed from the ground up for enterprise operational security. No SaaS integrations, no API surface, no codebase exposure."
              align="left"
            />
          </div>

          {/* Feature grid */}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            {FEATURES.map((f, i) => (
              <Reveal key={f.title} delay={i * 0.07} direction="right">
                <div className="flex flex-col gap-3 rounded-xl border border-white/6 bg-[#0f1620] p-5">
                  <span className="text-xl">{f.icon}</span>
                  <div>
                    <h4 className="mb-1 text-sm font-semibold text-white">{f.title}</h4>
                    <p className="text-xs leading-relaxed text-[#9ba3af]">{f.desc}</p>
                  </div>
                </div>
              </Reveal>
            ))}
          </div>
        </div>
      </div>
    </section>
  )
}
