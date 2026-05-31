import { Reveal } from '../primitives/Reveal'
import { SectionHeader } from '../primitives/SectionHeader'

const STATS = [
  {
    value: '~97%',
    label: 'Fewer LLM tokens',
    desc: 'Deterministic execution means Claude is only invoked when truly needed — not for every step.',
  },
  {
    value: '5',
    label: 'Recovery layers',
    desc: 'Layered self-healing from simple selector fallback all the way to vision-based AI recovery.',
  },
  {
    value: '1×',
    label: 'Human-paced speed',
    desc: 'Executes at natural human speed — no bot detection, no rate limiting, no CAPTCHAs.',
  },
  {
    value: '0',
    label: 'APIs required',
    desc: 'If a human can navigate it in a browser, CONXA can operate it. No integrations needed.',
  },
]

export function Reliability() {
  return (
    <section className="relative bg-[#06080b] px-6 py-28">
      <div className="mx-auto max-w-5xl">
        <SectionHeader
          eyebrow="Enterprise-grade reliability"
          headline="Reliable enough to trust with operations."
          sub="Engineered for production. Designed for the workflows that cannot afford to fail."
        />

        <div className="mt-16 grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
          {STATS.map((stat, i) => (
            <Reveal key={stat.label} delay={i * 0.08}>
              <div className="flex flex-col gap-3 rounded-2xl border border-white/6 bg-[#0b0f14] p-6">
                <p
                  className="text-4xl font-bold tracking-tight"
                  style={{ backgroundImage: 'linear-gradient(135deg, #22d3ee, #5eead4)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}
                >
                  {stat.value}
                </p>
                <div>
                  <p className="mb-1 text-sm font-semibold text-white">{stat.label}</p>
                  <p className="text-xs leading-relaxed text-[#9ba3af]">{stat.desc}</p>
                </div>
              </div>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  )
}
