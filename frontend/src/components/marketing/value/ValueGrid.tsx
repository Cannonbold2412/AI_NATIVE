import { Reveal } from '../primitives/Reveal'
import { SectionHeader } from '../primitives/SectionHeader'
import { ValueCard } from './ValueCard'

const VALUES = [
  {
    icon: '⚡',
    headline: '~97% Less Token Usage',
    body: 'Execution is deterministic and code-driven. Claude is only invoked when recovery or reasoning is genuinely needed — not for every step.',
  },
  {
    icon: '🛡',
    headline: '5-Layer Recovery System',
    body: 'Selector fallbacks → anchor targeting → LLM intent recovery → vision recovery → graceful terminal state. CONXA always has a next move.',
  },
  {
    icon: '🚶',
    headline: 'Human-Speed Execution',
    body: 'CONXA operates at the pace of a trained human operator — avoiding bot detection, rate limits, and CAPTCHAs by design.',
  },
  {
    icon: '📊',
    headline: 'Full Observability',
    body: 'Track every run: who executed what, which skill ran, which step failed, which recovery layer was used, and the complete execution timeline.',
  },
  {
    icon: '🔒',
    headline: 'Internal Platform Support',
    body: 'Operate internal SaaS tools securely. No codebase exposure, no API keys shared, no platform integration required.',
  },
  {
    icon: '🎤',
    headline: 'No Coding Required',
    body: 'Simply teach workflows by demonstration — just like training a human employee. Users never touch APIs, configs, or codebases.',
  },
  {
    icon: '✏️',
    headline: 'Human Editing Layer',
    body: 'After recording, refine AI-interpreted steps in our visual editor. Fix interpretation errors and add conditions before deploying.',
  },
  {
    icon: '🔄',
    headline: 'Fast UI Adaptation',
    body: 'When a SaaS platform updates its UI, simply reteach the affected workflow in minutes — no engineer needed.',
  },
]

export function ValueGrid() {
  return (
    <section className="relative bg-[#06080b] px-6 py-28">
      <div className="mx-auto max-w-6xl">
        <SectionHeader
          eyebrow="Platform advantages"
          headline="Built differently by design."
          sub="Every decision in CONXA is made to make AI-operated workflows reliable, observable, and maintainable."
        />

        <div className="mt-16 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {VALUES.map((v, i) => (
            <Reveal key={v.headline} delay={i * 0.06}>
              <ValueCard {...v} />
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  )
}
