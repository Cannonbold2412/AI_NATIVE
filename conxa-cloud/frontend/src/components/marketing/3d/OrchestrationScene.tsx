'use client'

import { useRef, useMemo } from 'react'
import { Canvas, useFrame } from '@react-three/fiber'
import * as THREE from 'three'

function Nodes() {
  const count = 18
  const meshRef = useRef<THREE.InstancedMesh>(null)
  const dummy = useMemo(() => new THREE.Object3D(), [])

  const positions = useMemo(() => {
    return Array.from({ length: count }, (_, i) => {
      const theta = (i / count) * Math.PI * 2
      const r = 2.2 + Math.sin(i * 1.3) * 0.8
      return new THREE.Vector3(
        Math.cos(theta) * r,
        Math.sin(i * 0.7) * 0.9,
        Math.sin(theta) * r,
      )
    })
  }, [])

  useFrame(({ clock }) => {
    const t = clock.getElapsedTime() * 0.2
    positions.forEach((pos, i) => {
      dummy.position.set(
        pos.x + Math.sin(t + i) * 0.15,
        pos.y + Math.cos(t * 0.8 + i) * 0.1,
        pos.z + Math.cos(t + i * 1.2) * 0.15,
      )
      dummy.scale.setScalar(0.08 + Math.abs(Math.sin(t * 2 + i)) * 0.04)
      dummy.updateMatrix()
      meshRef.current?.setMatrixAt(i, dummy.matrix)
    })
    if (meshRef.current) meshRef.current.instanceMatrix.needsUpdate = true
  })

  return (
    <instancedMesh ref={meshRef} args={[undefined, undefined, count]}>
      <sphereGeometry args={[1, 8, 8]} />
      <meshBasicMaterial color="#22d3ee" transparent opacity={0.6} />
    </instancedMesh>
  )
}

function Edges() {
  const linesRef = useRef<THREE.LineSegments>(null)

  const { geometry } = useMemo(() => {
    const positions: number[] = []
    const count = 18
    const pts = Array.from({ length: count }, (_, i) => {
      const theta = (i / count) * Math.PI * 2
      const r = 2.2 + Math.sin(i * 1.3) * 0.8
      return new THREE.Vector3(Math.cos(theta) * r, Math.sin(i * 0.7) * 0.9, Math.sin(theta) * r)
    })

    for (let i = 0; i < count; i++) {
      const next = (i + 1) % count
      const skip = (i + 3) % count
      positions.push(...pts[i].toArray(), ...pts[next].toArray())
      if (i % 3 === 0) positions.push(...pts[i].toArray(), ...pts[skip].toArray())
    }

    const geo = new THREE.BufferGeometry()
    geo.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3))
    return { geometry: geo }
  }, [])

  useFrame(({ clock }) => {
    if (linesRef.current?.material) {
      const mat = linesRef.current.material as THREE.LineBasicMaterial
      mat.opacity = 0.06 + Math.abs(Math.sin(clock.getElapsedTime() * 0.5)) * 0.08
    }
  })

  return (
    <lineSegments ref={linesRef} geometry={geometry}>
      <lineBasicMaterial color="#22d3ee" transparent opacity={0.08} />
    </lineSegments>
  )
}

export function OrchestrationScene() {
  return (
    <Canvas
      camera={{ position: [0, 2, 7], fov: 50 }}
      gl={{ antialias: true, alpha: true }}
      style={{ background: 'transparent' }}
      frameloop="always"
    >
      <ambientLight intensity={0.2} />
      <Nodes />
      <Edges />
    </Canvas>
  )
}
