'use client'

import { motion } from 'framer-motion'

interface CursorProps {
  x: number
  y: number
  clicking: boolean
}

export function Cursor({ x, y, clicking }: CursorProps) {
  return (
    <motion.div
      className="pointer-events-none absolute z-50"
      animate={{ left: `${x}%`, top: `${y}%` }}
      transition={{ type: 'spring', stiffness: 60, damping: 18 }}
      style={{ translateX: '-50%', translateY: '-50%' }}
    >
      {/* Cursor icon */}
      <svg width="18" height="22" viewBox="0 0 18 22" fill="none">
        <path
          d="M1 1l6.5 16L9.5 11l6.5-1.5L1 1z"
          fill="white"
          stroke="#06080b"
          strokeWidth="1.5"
          strokeLinejoin="round"
        />
      </svg>

      {/* Click ripple */}
      {clicking && (
        <motion.div
          className="absolute -inset-4 rounded-full border border-cyan-400/60"
          initial={{ scale: 0, opacity: 0.8 }}
          animate={{ scale: 1.6, opacity: 0 }}
          transition={{ duration: 0.45, ease: 'easeOut' }}
        />
      )}
    </motion.div>
  )
}
