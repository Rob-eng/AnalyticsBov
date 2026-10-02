import { useEffect, useRef, useState } from 'react'
import { fmtMonth, fmtNdvi, type NdviPoint } from './api'

// NDVI mensal: linha = média sobre o perímetro; faixa = 25%–75% dos pixels (homogeneidade do pasto).
// Meses sem cena limpa ficam como lacuna (a linha não liga pontos sem dado).
const H = 150
const PAD = { l: 30, r: 8, t: 10, b: 22 }
const Y_MAX = 0.9
const LINE = '#2E7D32'
const ZONE = '#2A6FB0'   // ponto/piquete: segunda série, mesmo eixo

type Props = { series: NdviPoint[]; selected: string[]; onPick: (month: string) => void; zone?: NdviPoint[] | null; zoneLabel?: string }

export default function NdviChart({ series, selected, onPick, zone, zoneLabel = 'Ponto' }: Props) {
  const box = useRef<HTMLDivElement>(null)
  const [w, setW] = useState(300)
  const [hover, setHover] = useState<number | null>(null)

  useEffect(() => {
    if (!box.current) return
    const ro = new ResizeObserver(([e]) => setW(Math.max(220, e.contentRect.width)))
    ro.observe(box.current)
    return () => ro.disconnect()
  }, [])

  const n = series.length
  const iw = w - PAD.l - PAD.r
  const ih = H - PAD.t - PAD.b
  const x = (i: number) => PAD.l + (n <= 1 ? iw / 2 : (i / (n - 1)) * iw)
  const y = (v: number) => PAD.t + ih - (Math.min(Math.max(v, 0), Y_MAX) / Y_MAX) * ih

  // segmentos contínuos (quebra onde não há dado)
  const segmentsOf = (s: NdviPoint[]) => {
    const out: number[][] = []
    s.forEach((p, i) => {
      if (p.mean == null) return
      const last = out[out.length - 1]
      if (last && last[last.length - 1] === i - 1) last.push(i); else out.push([i])
    })
    return out
  }
  const pathOf = (s: NdviPoint[]) => segmentsOf(s).map(seg => seg.map((i, k) => `${k ? 'L' : 'M'}${x(i)},${y(s[i].mean!)}`).join('')).join('')
  const segments = segmentsOf(series)
  const linePath = pathOf(series)
  const zoneByMonth = new Map((zone ?? []).map(p => [p.month, p]))
  const zoneAligned = zone ? series.map(p => zoneByMonth.get(p.month) ?? { ...p, mean: null }) : null
  const bandPath = segments.map(seg => {
    const top = seg.map((i, k) => `${k ? 'L' : 'M'}${x(i)},${y(series[i].p75 ?? series[i].mean!)}`).join('')
    const bottom = [...seg].reverse().map(i => `L${x(i)},${y(series[i].p25 ?? series[i].mean!)}`).join('')
    return `${top}${bottom}Z`
  }).join('')

  const onMove = (e: React.MouseEvent<SVGRectElement>) => {
    const r = e.currentTarget.getBoundingClientRect()
    const i = Math.round(((e.clientX - r.left) / r.width) * (n - 1))
    setHover(Math.min(n - 1, Math.max(0, i)))
  }
  const hp = hover != null ? series[hover] : null
  const labelEvery = Math.ceil(n / Math.max(2, Math.floor(iw / 48)))

  return (
    <div className="chart" ref={box}>
      <svg width={w} height={H} role="img" aria-label="NDVI médio mensal sobre o perímetro">
        {[0, 0.3, 0.6, 0.9].map(t => (
          <g key={t}>
            <line x1={PAD.l} x2={w - PAD.r} y1={y(t)} y2={y(t)} className="chart-grid" />
            <text x={PAD.l - 6} y={y(t) + 3} className="chart-tick" textAnchor="end">{t.toFixed(1).replace('.', ',')}</text>
          </g>
        ))}
        {series.map((p, i) => ((i % labelEvery === 0 && n - 1 - i >= labelEvery * 0.7) || i === n - 1) && (
          <text key={p.month} x={x(i)} y={H - 6} className="chart-tick" textAnchor="middle">{fmtMonth(p.month)}</text>
        ))}
        <path d={bandPath} fill={LINE} opacity={0.14} />
        <path d={linePath} fill="none" stroke={LINE} strokeWidth={2} strokeLinejoin="round" />
        {zoneAligned && <path d={pathOf(zoneAligned)} fill="none" stroke={ZONE} strokeWidth={2} strokeLinejoin="round" />}
        {series.map((p, i) => p.mean != null && selected.includes(p.month) && (
          <circle key={p.month} cx={x(i)} cy={y(p.mean)} r={5} fill="#E8B730" stroke="#17251C" strokeWidth={2} />
        ))}
        {hp && hp.mean != null && (
          <>
            <line x1={x(hover!)} x2={x(hover!)} y1={PAD.t} y2={PAD.t + ih} className="chart-cross" />
            <circle cx={x(hover!)} cy={y(hp.mean)} r={4} fill={LINE} stroke="#fff" strokeWidth={2} />
            {zoneAligned?.[hover!]?.mean != null && <circle cx={x(hover!)} cy={y(zoneAligned[hover!].mean!)} r={4} fill={ZONE} stroke="#fff" strokeWidth={2} />}
          </>
        )}
        <rect x={PAD.l} y={PAD.t} width={iw} height={ih} fill="transparent" style={{ cursor: 'pointer' }}
          onMouseMove={onMove} onMouseLeave={() => setHover(null)}
          onClick={() => { if (hp && hp.mean != null) onPick(hp.month) }} />
      </svg>
      {hp && (
        <div className="chart-tip" style={{ left: Math.min(Math.max(x(hover!) - 70, 0), w - 140) }}>
          <strong>{fmtMonth(hp.month)}</strong>
          {hp.mean == null
            ? <span>sem imagem sem nuvens</span>
            : <><span>{zoneAligned ? 'Fazenda ' : 'NDVI '}{fmtNdvi(hp.mean)}</span>
                {zoneAligned && <span>{zoneLabel} {fmtNdvi(zoneAligned[hover!]?.mean ?? null)}</span>}
                <span className="muted">faixa {fmtNdvi(hp.p25)}–{fmtNdvi(hp.p75)} · {hp.images} cenas</span></>}
        </div>
      )}
      {zoneAligned && (
        <div className="chart-legend">
          <span><i style={{ background: LINE }} />Fazenda (média)</span>
          <span><i style={{ background: ZONE }} />{zoneLabel}</span>
        </div>
      )}
    </div>
  )
}
