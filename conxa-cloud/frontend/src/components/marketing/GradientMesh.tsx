export function GradientMesh() {
  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden" aria-hidden>
      {/* Primary cyan orb — top left */}
      <div
        className="absolute -left-[20%] -top-[10%] h-[60vh] w-[60vw] rounded-full opacity-[0.12]"
        style={{
          background: 'radial-gradient(circle, #22d3ee 0%, transparent 70%)',
          filter: 'blur(80px)',
        }}
      />
      {/* Teal orb — center right */}
      <div
        className="absolute right-[-10%] top-[30%] h-[50vh] w-[50vw] rounded-full opacity-[0.08]"
        style={{
          background: 'radial-gradient(circle, #5eead4 0%, transparent 70%)',
          filter: 'blur(100px)',
        }}
      />
      {/* Deep blue orb — bottom */}
      <div
        className="absolute bottom-[-5%] left-[30%] h-[40vh] w-[40vw] rounded-full opacity-[0.06]"
        style={{
          background: 'radial-gradient(circle, #0e7490 0%, transparent 70%)',
          filter: 'blur(120px)',
        }}
      />
    </div>
  )
}
