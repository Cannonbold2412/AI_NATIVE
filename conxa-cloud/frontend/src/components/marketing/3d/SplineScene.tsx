'use client'

import { Suspense } from 'react'
import dynamic from 'next/dynamic'

// Replace this URL with your own hosted Spline scene
const SPLINE_SCENE_URL = ''

const Spline = dynamic(() => import('@splinetool/react-spline'), { ssr: false })

export function SplineScene() {
  if (!SPLINE_SCENE_URL) return null

  return (
    <Suspense fallback={null}>
      <Spline scene={SPLINE_SCENE_URL} className="h-full w-full" />
    </Suspense>
  )
}
