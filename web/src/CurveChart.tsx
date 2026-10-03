import { useEffect, useRef, useState } from 'react'
import { fmtBRL, fmtMonth, type CurveSession } from './api'

// Curva projetada: últimos pregões sobrepostos (o mais recente forte, os anteriores esmaecidos).
// Boi contínuo, vaca e novilha tracejados (codificação secundária além da cor).
export const CAT_STYLE = {
  boi: { color: '#2A6FB0', dash: undefined, label: 'Boi' },
  novilha: { color: '#7B4FA0', dash: '2 3', label: 'Novilha' },
  vaca: { color: '#D9822B', dash: '6 4', label: 'Vaca' },
} as const
type Cat = keyof typeof CAT_STYLE
const CATS: Cat[] = ['boi', 'novilha', 'vaca']
const H = 300
const PAD = { l: 52, r: 74, t: 14, b: 28 }

export default function CurveChart({ sessions }: { sessions: CurveSession[] }) {
  const box = useRef<HTMLDivElement>(null)
  const [w, setW] = useState(640)
  const [hover, setHover] = useState<number | null>(null)
  useEffect(() => {
    if (!box.current) return
    const ro = new ResizeObserver(([e]) => setW(Math.max(320, e.contentRect.width)))
    ro.observe(box.current)
    return () => ro.disconnect()
  }, [])
  if (!sessions.length) return <p className="muted">Curva indisponível para esta praça.</p>

  const latest = sessions[sessions.length - 1]
  const months = [...new Set(sessions.flatMap(s => s.curve.boi.map(p => p[0])))].sort()
  const all = sessions.flatMap(s => CATS.flatMap(c => s.curve[c].map(p => p[1])))
  const lo = Math.floor((Math.min(...all) - 5) / 10) * 10, hi = Math.ceil((Math.max(...all) + 5) / 10) * 10
  const iw = w - PAD.l - PAD.r, ih = H - PAD.t - PAD.b
  const x = (m: string) => PAD.l + (months.length < 2 ? iw / 2 : (months.indexOf(m) / (months.length - 1)) * iw)
  const y = (v: number) => PAD.t + ih - ((v - lo) / (hi - lo)) * ih
  const path = (pts: [string, number][]) => pts.map((p, i) => `${i ? 'L' : 'M'}${x(p[0])},${y(p[1])}`).join('')
  const ticks = Array.from({ length: 5 }, (_, i) => lo + ((hi - lo) / 4) * i)
  const step = Math.ceil(months.length / Math.max(2, Math.floor(iw / 56)))
  const n = sessions.length

  // rótulos diretos no fim das curvas do último pregão, afastados para não se sobreporem
  const ends = CATS.map(c => ({ c, v: latest.curve[c][latest.curve[c].length - 1][1] })).sort((a, b) => b.v - a.v)
  let lastY = -Infinity
  const labelY = ends.map(e => { const yy = Math.max(y(e.v), lastY + 14); lastY = yy; return { ...e, yy } })

  const onMove = (ev: React.MouseEvent<SVGRectElement>) => {
    const r = ev.currentTarget.getBoundingClientRect()
    const i = Math.round(((ev.clientX - r.left) / r.width) * (months.length - 1))
    setHover(Math.min(months.length - 1, Math.max(0, i)))
  }
  const hm = hover != null ? months[hover] : null

  return (
    <div className="chart curve-chart" ref={box}>
      <svg width={w} height={H} role="img" aria-label={`Curva projetada de preços, ${n} pregões`}>
        {ticks.map(t => (
          <g key={t}>
            <line x1={PAD.l} x2={w - PAD.r} y1={y(t)} y2={y(t)} className="chart-grid" />
            <text x={PAD.l - 8} y={y(t) + 4} className="chart-tick" textAnchor="end">{Math.round(t)}</text>
          </g>
        ))}
        {months.map((m, i) => (i % step === 0 || i === months.length - 1) && (
          <text key={m} x={x(m)} y={H - 8} className="chart-tick" textAnchor="middle">{fmtMonth(m)}</text>
        ))}
        {sessions.map((s, si) => CATS.map(c => (
          <path key={s.session_date + c} d={path(s.curve[c])} fill="none" stroke={CAT_STYLE[c].color}
            strokeDasharray={CAT_STYLE[c].dash} strokeWidth={si === n - 1 ? 2.4 : 1.2}
            opacity={si === n - 1 ? 1 : 0.12 + (0.38 * si) / Math.max(1, n - 2)} strokeLinejoin="round" />
        )))}
        {labelY.map(l => (
          <text key={l.c} x={w - PAD.r + 6} y={l.yy + 4} className="curve-label">{CAT_STYLE[l.c].label} {Math.round(l.v)}</text>
        ))}
        {hm && <line x1={x(hm)} x2={x(hm)} y1={PAD.t} y2={PAD.t + ih} className="chart-cross" />}
        {hm && CATS.map(c => {
          const p = latest.curve[c].find(q => q[0] === hm)
          return p ? <circle key={c} cx={x(hm)} cy={y(p[1])} r={4} fill={CAT_STYLE[c].color} stroke="#fff" strokeWidth={2} /> : null
        })}
        <rect x={PAD.l} y={PAD.t} width={iw} height={ih} fill="transparent" onMouseMove={onMove} onMouseLeave={() => setHover(null)} />
      </svg>
      {hm && (
        <div className="chart-tip" style={{ left: Math.min(Math.max(x(hm) - 80, 0), w - 170) }}>
          <strong>{fmtMonth(hm)} · pregão {latest.session_date.split('-').reverse().slice(0, 2).join('/')}</strong>
          {CATS.map(c => { const p = latest.curve[c].find(q => q[0] === hm); return p && <span key={c}>{CAT_STYLE[c].label} {fmtBRL(p[1])}/@</span> })}
          {n > 1 && (() => { const p0 = sessions[0].curve.boi.find(q => q[0] === hm), p1 = latest.curve.boi.find(q => q[0] === hm)
            return p0 && p1 ? <span className="muted">Boi {p1[1] - p0[1] >= 0 ? '+' : ''}{(p1[1] - p0[1]).toFixed(2).replace('.', ',')} desde {sessions[0].session_date.split('-').reverse().slice(0, 2).join('/')}</span> : null })()}
        </div>
      )}
      <div className="chart-legend">
        {CATS.map(c => (
          <span key={c}><svg width="22" height="8" aria-hidden="true"><line x1="0" x2="22" y1="4" y2="4" stroke={CAT_STYLE[c].color} strokeWidth="2.4" strokeDasharray={CAT_STYLE[c].dash} /></svg>{CAT_STYLE[c].label}</span>
        ))}
        <span className="muted">linha forte = pregão de {latest.session_date.split('-').reverse().join('/')}; claras = {n - 1} anteriores</span>
      </div>
    </div>
  )
}
