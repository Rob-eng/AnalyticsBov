import { useEffect, useRef, useState } from 'react'

// Barras simples (uma série) com dica ao passar o mouse e linha de referência opcional.
export type Bar = { label: string; value: number; tip: string }
type Props = { bars: Bar[]; color: string; height?: number; ref_?: { value: number; label: string }; unit: string; ariaLabel: string }

const PAD = { l: 30, r: 6, t: 10, b: 20 }

export default function BarChart({ bars, color, height = 130, ref_, unit, ariaLabel }: Props) {
  const box = useRef<HTMLDivElement>(null)
  const [w, setW] = useState(300)
  const [hover, setHover] = useState<number | null>(null)
  useEffect(() => {
    if (!box.current) return
    const ro = new ResizeObserver(([e]) => setW(Math.max(220, e.contentRect.width)))
    ro.observe(box.current)
    return () => ro.disconnect()
  }, [])

  const n = bars.length
  const iw = w - PAD.l - PAD.r
  const ih = height - PAD.t - PAD.b
  const max = Math.max(1, ref_?.value ?? 0, ...bars.map(b => b.value)) * 1.1
  const step = iw / Math.max(1, n)
  const bw = Math.max(3, Math.min(28, step - 2))       // 2px de respiro entre barras
  const y = (v: number) => PAD.t + ih - (v / max) * ih
  const ticks = [0, max / 2, max].map(v => Math.round(v))
  const labelEvery = Math.ceil(n / Math.max(2, Math.floor(iw / 40)))

  return (
    <div className="chart" ref={box}>
      <svg width={w} height={height} role="img" aria-label={ariaLabel}>
        {ticks.map(t => (
          <g key={t}>
            <line x1={PAD.l} x2={w - PAD.r} y1={y(t)} y2={y(t)} className="chart-grid" />
            <text x={PAD.l - 6} y={y(t) + 3} className="chart-tick" textAnchor="end">{t}</text>
          </g>
        ))}
        {bars.map((b, i) => {
          const x = PAD.l + i * step + (step - bw) / 2
          const h = Math.max(b.value > 0 ? 2 : 0, PAD.t + ih - y(b.value))
          return (
            <g key={i}>
              <rect x={x} y={PAD.t + ih - h} width={bw} height={h} rx={Math.min(4, bw / 2)} fill={color} opacity={hover == null || hover === i ? 1 : 0.55} />
              {(i % labelEvery === 0 && n - 1 - i >= labelEvery * 0.7 || i === n - 1) &&
                <text x={x + bw / 2} y={height - 6} className="chart-tick" textAnchor="middle">{b.label}</text>}
              <rect x={PAD.l + i * step} y={PAD.t} width={step} height={ih} fill="transparent"
                onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)} />
            </g>
          )
        })}
        {ref_ && (
          <g>
            <line x1={PAD.l} x2={w - PAD.r} y1={y(ref_.value)} y2={y(ref_.value)} className="chart-ref" />
            <text x={PAD.l + 3} y={y(ref_.value) - 4} className="chart-tick" textAnchor="start">{ref_.label}</text>
          </g>
        )}
      </svg>
      {hover != null && (
        <div className="chart-tip" style={{ left: Math.min(Math.max(PAD.l + hover * step + step / 2 - 70, 0), w - 140) }}>
          <strong>{bars[hover].label}</strong><span>{bars[hover].value.toLocaleString('pt-BR', { maximumFractionDigits: 1 })} {unit}</span>
          <span className="muted">{bars[hover].tip}</span>
        </div>
      )}
    </div>
  )
}
