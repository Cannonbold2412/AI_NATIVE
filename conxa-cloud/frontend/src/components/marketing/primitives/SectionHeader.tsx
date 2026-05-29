import { Reveal } from './Reveal'

interface SectionHeaderProps {
  eyebrow?: string
  headline: string
  sub?: string
  align?: 'left' | 'center'
  className?: string
}

export function SectionHeader({ eyebrow, headline, sub, align = 'center', className }: SectionHeaderProps) {
  const alignClass = align === 'center' ? 'text-center items-center' : 'text-left items-start'

  return (
    <div className={`flex flex-col gap-4 ${alignClass} ${className ?? ''}`}>
      {eyebrow && (
        <Reveal>
          <span className="inline-flex items-center gap-2 rounded-full border border-[rgba(34,211,238,0.2)] bg-[rgba(34,211,238,0.06)] px-3 py-1 text-xs font-medium uppercase tracking-widest text-cyan-400">
            {eyebrow}
          </span>
        </Reveal>
      )}
      <Reveal delay={0.05}>
        <h2 className="max-w-3xl text-3xl font-semibold tracking-tight text-[#f4f5f7] sm:text-4xl lg:text-5xl">
          {headline}
        </h2>
      </Reveal>
      {sub && (
        <Reveal delay={0.1}>
          <p className="max-w-2xl text-base text-[#9ba3af] sm:text-lg leading-relaxed">
            {sub}
          </p>
        </Reveal>
      )}
    </div>
  )
}
