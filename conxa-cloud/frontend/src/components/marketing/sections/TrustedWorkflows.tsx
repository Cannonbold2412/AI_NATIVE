'use client'

import { motion } from 'framer-motion'
import { Reveal } from '../primitives/Reveal'

const PLATFORMS = [
  'Salesforce', 'ServiceNow', 'Workday', 'SAP', 'Zendesk',
  'NetSuite', 'Jira', 'Confluence', 'Notion', 'HubSpot',
  'Okta', 'GitHub', 'Linear', 'Intercom', 'Stripe',
]

export function TrustedWorkflows() {
  const doubled = [...PLATFORMS, ...PLATFORMS]

  return (
    <section className="relative overflow-hidden border-y border-white/6 bg-[#0b0f14] py-16">
      <div className="mb-8 text-center">
        <Reveal>
          <p className="text-xs font-medium uppercase tracking-widest text-[#6b7280]">
            Executes workflows across your entire stack
          </p>
        </Reveal>
      </div>

      {/* Marquee */}
      <div className="relative flex overflow-hidden [mask-image:linear-gradient(to_right,transparent,black_10%,black_90%,transparent)]">
        <motion.div
          className="flex shrink-0 gap-8 pr-8"
          animate={{ x: ['0%', '-50%'] }}
          transition={{ duration: 28, ease: 'linear', repeat: Infinity }}
        >
          {doubled.map((name, i) => (
            <div
              key={`${name}-${i}`}
              className="flex shrink-0 items-center gap-2 rounded-full border border-white/8 bg-[#0f1620] px-5 py-2"
            >
              <div className="h-1.5 w-1.5 rounded-full bg-cyan-400/60" />
              <span className="whitespace-nowrap text-sm text-[#9ba3af]">{name}</span>
            </div>
          ))}
        </motion.div>
      </div>
    </section>
  )
}
