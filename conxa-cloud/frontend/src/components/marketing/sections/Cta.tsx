import { GlowButton } from '../primitives/GlowButton'
import { Reveal } from '../primitives/Reveal'

export function Cta() {
  return (
    <section className="relative overflow-hidden bg-[#0b0f14] px-6 py-32">
      {/* Centered glow */}
      <div
        className="pointer-events-none absolute left-1/2 top-1/2 h-[500px] w-[500px] -translate-x-1/2 -translate-y-1/2 rounded-full opacity-[0.08]"
        style={{ background: 'radial-gradient(circle, #22d3ee, transparent 70%)', filter: 'blur(80px)' }}
      />

      <div className="relative mx-auto max-w-3xl text-center">
        <Reveal>
          <span className="mb-6 inline-flex items-center gap-2 rounded-full border border-cyan-400/20 bg-cyan-400/6 px-4 py-1.5 text-xs font-medium tracking-wide text-cyan-400">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-cyan-400" />
            Now in early access
          </span>
        </Reveal>

        <Reveal delay={0.06}>
          <h2
            className="mb-5 font-semibold tracking-tight text-[#f4f5f7]"
            style={{ fontSize: 'clamp(2rem, 5vw, 3.5rem)', lineHeight: 1.1 }}
          >
            Hire your first{' '}
            <span
              className="bg-clip-text text-transparent"
              style={{ backgroundImage: 'linear-gradient(135deg, #22d3ee, #5eead4)' }}
            >
              AI operator.
            </span>
          </h2>
        </Reveal>

        <Reveal delay={0.1}>
          <p className="mb-10 text-base leading-relaxed text-[#9ba3af] sm:text-lg">
            Start teaching CONXA your workflows today. No engineering team required — just demonstrate, refine, and package.
          </p>
        </Reveal>

        <Reveal delay={0.14}>
          <div className="flex flex-wrap items-center justify-center gap-4">
            <GlowButton href="/sign-up">Get started free</GlowButton>
            <GlowButton href="mailto:founders@conxa.in" variant="ghost">Talk to founders</GlowButton>
          </div>
        </Reveal>
      </div>
    </section>
  )
}
