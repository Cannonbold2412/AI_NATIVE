import { SectionHeader } from '../primitives/SectionHeader'
import { Reveal } from '../primitives/Reveal'

const RUNS = [
  { user: 'sarah.chen', plugin: 'hr-onboarding', skill: 'create-employee', status: 'success', recovery: null, time: '2m 14s', ago: '3m ago' },
  { user: 'james.okafor', plugin: 'access-control', skill: 'role-assignment', status: 'recovered', recovery: 'L2 Anchor', time: '3m 41s', ago: '11m ago' },
  { user: 'priya.shah', plugin: 'payroll-sync', skill: 'sync-employee', status: 'success', recovery: null, time: '1m 08s', ago: '22m ago' },
  { user: 'tom.vargas', plugin: 'finance-ops', skill: 'create-cost-center', status: 'success', recovery: null, time: '4m 02s', ago: '35m ago' },
  { user: 'mei.lin', plugin: 'email-admin', skill: 'send-welcome', status: 'recovered', recovery: 'L1 Selector', time: '2m 55s', ago: '1h ago' },
]

const STATS = [
  { label: 'Runs today', value: '248', delta: '+12%' },
  { label: 'Success rate', value: '98.7%', delta: '+0.4%' },
  { label: 'Avg duration', value: '2m 31s', delta: '-18s' },
  { label: 'Recoveries', value: '6', delta: '–' },
]

export function AnalyticsDashboard() {
  return (
    <section className="relative bg-[#06080b] px-6 py-28">
      <div className="mx-auto max-w-6xl">
        <SectionHeader
          eyebrow="Operational analytics"
          headline="Every run, accounted for."
          sub="Complete audit trail: who ran what, which skill failed, exact recovery layer, and full execution timeline."
        />

        <Reveal delay={0.1}>
          <div className="mt-16 overflow-hidden rounded-2xl border border-white/6 bg-[#0b0f14]">
            {/* Dashboard header */}
            <div className="flex h-10 items-center gap-3 border-b border-white/6 bg-[#0f1620] px-4">
              <div className="flex gap-1.5">
                <div className="h-2.5 w-2.5 rounded-full bg-red-500/40" />
                <div className="h-2.5 w-2.5 rounded-full bg-yellow-500/40" />
                <div className="h-2.5 w-2.5 rounded-full bg-green-500/40" />
              </div>
              <span className="text-xs text-[#6b7280]">CONXA — Operational Dashboard</span>
            </div>

            <div className="p-6">
              {/* Stats row */}
              <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
                {STATS.map((stat) => (
                  <div key={stat.label} className="rounded-xl border border-white/6 bg-[#0f1620] p-4">
                    <p className="mb-1 text-[10px] uppercase tracking-widest text-[#6b7280]">{stat.label}</p>
                    <p className="text-2xl font-semibold tracking-tight text-white">{stat.value}</p>
                    <p className="mt-1 text-[10px] text-emerald-400">{stat.delta}</p>
                  </div>
                ))}
              </div>

              {/* Execution table */}
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-white/6">
                      {['User', 'Plugin', 'Skill', 'Status', 'Recovery', 'Duration', 'When'].map((h) => (
                        <th key={h} className="py-2 pr-4 text-left text-[10px] font-medium uppercase tracking-widest text-[#6b7280]">
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {RUNS.map((run, i) => (
                      <tr key={i} className="border-b border-white/4 hover:bg-white/2">
                        <td className="py-2.5 pr-4 text-[#9ba3af]">{run.user}</td>
                        <td className="py-2.5 pr-4 font-mono text-cyan-400/80">{run.plugin}</td>
                        <td className="py-2.5 pr-4 text-[#9ba3af]">{run.skill}</td>
                        <td className="py-2.5 pr-4">
                          <span
                            className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${
                              run.status === 'success'
                                ? 'bg-emerald-500/10 text-emerald-400'
                                : 'bg-amber-500/10 text-amber-400'
                            }`}
                          >
                            {run.status}
                          </span>
                        </td>
                        <td className="py-2.5 pr-4 text-[#6b7280]">
                          {run.recovery ? (
                            <span className="rounded bg-amber-500/10 px-1.5 py-0.5 text-[10px] text-amber-400">
                              {run.recovery}
                            </span>
                          ) : '—'}
                        </td>
                        <td className="py-2.5 pr-4 font-mono text-[#9ba3af]">{run.time}</td>
                        <td className="py-2.5 text-[#6b7280]">{run.ago}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Timeline sparkline (decorative) */}
              <div className="mt-6 rounded-xl border border-white/6 bg-[#0f1620] p-4">
                <p className="mb-3 text-[10px] uppercase tracking-widest text-[#6b7280]">Execution timeline — last 24h</p>
                <div className="flex h-12 items-end gap-1">
                  {[4, 7, 5, 9, 12, 8, 14, 11, 16, 13, 19, 15, 22, 18, 24, 20, 17, 21, 19, 23, 20, 24, 21, 19].map((h, i) => (
                    <div
                      key={i}
                      className="flex-1 rounded-sm opacity-80 hover:opacity-100 transition-opacity"
                      style={{
                        height: `${(h / 24) * 100}%`,
                        background: `linear-gradient(to top, #22d3ee, #5eead4)`,
                        minWidth: 4,
                      }}
                    />
                  ))}
                </div>
                <div className="mt-2 flex justify-between text-[10px] text-[#6b7280]">
                  <span>00:00</span>
                  <span>12:00</span>
                  <span>24:00</span>
                </div>
              </div>
            </div>
          </div>
        </Reveal>
      </div>
    </section>
  )
}
