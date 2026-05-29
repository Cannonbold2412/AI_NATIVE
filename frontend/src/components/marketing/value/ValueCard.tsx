'use client'

import { motion } from 'framer-motion'

interface ValueCardProps {
  icon: string
  headline: string
  body: string
}

export function ValueCard({ icon, headline, body }: ValueCardProps) {
  return (
    <motion.div
      className="group flex flex-col gap-4 rounded-2xl border border-white/6 bg-[#0b0f14] p-6 transition-all hover:border-white/12 hover:bg-[#0f1620]"
      whileHover={{ y: -2 }}
      transition={{ duration: 0.2 }}
    >
      <div className="flex h-10 w-10 items-center justify-center rounded-xl border border-white/8 bg-[#0f1620] text-lg">
        {icon}
      </div>
      <div>
        <h3 className="mb-1.5 text-sm font-semibold text-white">{headline}</h3>
        <p className="text-sm leading-relaxed text-[#9ba3af]">{body}</p>
      </div>
    </motion.div>
  )
}
