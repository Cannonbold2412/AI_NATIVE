'use client'

import { motion } from 'framer-motion'
import Link from 'next/link'

interface GlowButtonProps {
  href: string
  children: React.ReactNode
  variant?: 'primary' | 'ghost'
  className?: string
}

export function GlowButton({ href, children, variant = 'primary', className }: GlowButtonProps) {
  if (variant === 'primary') {
    return (
      <Link href={href}>
        <motion.span
          className={`relative inline-flex cursor-pointer items-center gap-2 rounded-lg px-6 py-3 text-sm font-semibold text-[#06080b] transition-all ${className ?? ''}`}
          style={{ background: 'linear-gradient(135deg, #22d3ee, #5eead4)' }}
          whileHover={{ scale: 1.02, boxShadow: '0 0 32px rgba(34,211,238,0.45)' }}
          whileTap={{ scale: 0.98 }}
        >
          {children}
        </motion.span>
      </Link>
    )
  }

  return (
    <Link href={href}>
      <motion.span
        className={`inline-flex cursor-pointer items-center gap-2 rounded-lg border border-white/10 px-6 py-3 text-sm font-medium text-[#9ba3af] transition-colors hover:border-white/20 hover:text-white ${className ?? ''}`}
        whileHover={{ scale: 1.01 }}
        whileTap={{ scale: 0.99 }}
      >
        {children}
      </motion.span>
    </Link>
  )
}
