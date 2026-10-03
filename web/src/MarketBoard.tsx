import { useQuery } from '@tanstack/react-query'
import { api, fmtBRL, type SpotSeries } from './api'
import CurveChart from './CurveChart'

const fmtDay = (d: string) => d.split('-').reverse().join('/')
const num = (v: number, nd = 2) => v.toLocaleString('pt-BR', { minimumFractionDigits: nd, maximumFractionDigits: nd })

function Spark({ h }: { h: [string, number][] }) {
  if (h.length < 2) return null
  const vs = h.map(p => p[1]), lo = Math.min(...vs), hi = Math.max(...vs), W = 72, H = 22
  const d = vs.map((v, i) => `${i ? 'L' : 'M'}${(i / (vs.length - 1)) * W},${H - 2 - ((v - lo) / (hi - lo || 1)) * (H - 4)}`).join('')
  return <svg className="spark" width={W} height={H} aria-hidden="true"><path d={d} fill="none" stroke="currentColor" strokeWidth="1.6" /></svg>
}

function SpotCard({ label, s, unit, nd = 2 }: { label: string; s?: SpotSeries; unit: string; nd?: number }) {
  if (!s) return null
  const up = (s.change ?? 0) > 0, down = (s.change ?? 0) < 0
  return (
    <div className="spot-card">
      <span className="spot-label">{label}</span>
      <strong className="spot-value">{unit === 'R$/@' ? fmtBRL(s.value) : num(s.value, nd)}<small>{unit === 'R$/@' ? '/@' : ` ${unit}`}</small></strong>
      <span className={'spot-change' + (up ? ' up' : down ? ' down' : '')}>
        {s.change == null ? '—' : `${up ? '▲' : down ? '▼' : '='} ${num(Math.abs(s.change), nd)}`}
        <Spark h={s.history} />
      </span>
    </div>
  )
}

export default function MarketBoard({ uf, onUf }: { uf: string; onUf: (uf: string) => void }) {
  const m = useQuery({ queryKey: ['market', uf], queryFn: () => api.market(uf) })
  const d = m.data
  if (m.isPending) return <div className="market"><p className="muted">Carregando cotações…</p></div>
  if (m.isError || !d) return <div className="market"><p className="notice">{(m.error as Error)?.message ?? 'Erro ao carregar o mercado.'}</p></div>
  const scotMax = Math.max(...d.scot.countries.map(c => c.usd), 1)
  const bandRows = [...new Set(d.cda.bands.map(b => b.band))]

  return (
    <div className="market">
      <header className="market-head">
        <div>
          <h1>Mercado · praça {d.uf}</h1>
          <p className="muted small">Indicadores DATAGRO de {d.spot.boi ? fmtDay(d.spot.boi.ref_date) : '—'} · variação contra a cotação anterior</p>
        </div>
        <label className="field market-uf"><span>Praça</span>
          <select className="input" value={d.uf} onChange={e => onUf(e.target.value)}>
            {d.ufs.map(u => <option key={u} value={u}>{u}</option>)}
          </select>
        </label>
      </header>

      <section className="spot-grid">
        <SpotCard label="Boi gordo" s={d.spot.boi} unit="R$/@" />
        <SpotCard label="Vaca gorda" s={d.spot.vaca} unit="R$/@" />
        <SpotCard label="Novilha" s={d.spot.novilha} unit="R$/@" />
        <SpotCard label="Escala de abate" s={d.spot.escala} unit="dias" nd={1} />
        <SpotCard label="Bônus (boi China)" s={d.spot.bonus} unit="R$/@" />
        <SpotCard label="Diferencial vs SP" s={d.spot.diferencial} unit="%" nd={1} />
      </section>

      <section className="market-card market-wide">
        <h2>Curva projetada — {d.uf}</h2>
        <p className="muted small">Boi pelos ajustes do futuro B3 ajustados à praça; vaca e novilha pela relação com o boi à vista ({d.curve.at(-1)?.methods.vaca ?? '—'}). Passe o mouse para ver os valores.</p>
        <CurveChart sessions={d.curve} />
      </section>

      <div className="market-cols">
        <section className="market-card">
          <h2>Praças</h2>
          <table className="mini-table praça-table">
            <thead><tr><th>Praça</th><th>Boi</th><th>Vaca</th><th>Novilha</th><th>Escala</th></tr></thead>
            <tbody>{d.praças.map(p => (
              <tr key={p.uf} className={p.uf === d.uf ? 'row-on' : ''} onClick={() => onUf(p.uf)} tabIndex={0} onKeyDown={e => { if (e.key === 'Enter') onUf(p.uf) }}>
                <td><strong>{p.uf}</strong></td><td>{p.boi ? num(p.boi) : '—'}</td><td>{p.vaca ? num(p.vaca) : '—'}</td>
                <td>{p.novilha ? num(p.novilha) : '—'}</td><td>{p.escala ? `${num(p.escala, 1)} d` : '—'}</td>
              </tr>
            ))}</tbody>
          </table>
          <p className="muted small">R$/@ · clique numa praça para ver a curva dela.</p>
        </section>

        <section className="market-card">
          <h2>Boi no mundo (Scot)</h2>
          <p className="muted small">US$/@ de carcaça · {d.scot.date ? fmtDay(d.scot.date) : '—'}</p>
          <ul className="bars">{d.scot.countries.map(c => (
            <li key={c.country} className={c.country === 'Brasil' ? 'bar-on' : ''}>
              <span className="bar-label">{c.country}</span>
              <span className="bar-track"><span className="bar-fill" style={{ width: `${(c.usd / scotMax) * 100}%` }} /></span>
              <span className="bar-value">{num(c.usd)}</span>
            </li>
          ))}</ul>
        </section>

        <section className="market-card">
          <h2>Reposição — leilões CDA</h2>
          <p className="muted small">R$/kg vivo, média ponderada por cabeças, últimos {d.cda.days} dias</p>
          <table className="mini-table">
            <thead><tr><th>Peso</th><th>Machos</th><th>Fêmeas</th></tr></thead>
            <tbody>{bandRows.map(band => {
              const m_ = d.cda.bands.find(b => b.band === band && b.sex === 'm'), f_ = d.cda.bands.find(b => b.band === band && b.sex === 'f')
              return <tr key={band}><td>{band}</td>
                <td>{m_ ? <>{num(m_.rkg)}<span className="cda-heads">{m_.heads.toLocaleString('pt-BR')} cab.</span></> : '—'}</td>
                <td>{f_ ? <>{num(f_.rkg)}<span className="cda-heads">{f_.heads.toLocaleString('pt-BR')} cab.</span></> : '—'}</td></tr>
            })}</tbody>
          </table>
          <ul className="occ-list cda-events">{d.cda.events.map(e => (
            <li key={e.name + e.date}>{fmtDay(e.date)} · {e.name}{e.heads ? ` · ${e.heads.toLocaleString('pt-BR')} cab.` : ''}</li>
          ))}</ul>
        </section>
      </div>
      <p className="muted small market-src">Fontes: DATAGRO, B3, Scot Consultoria e leilões CDA — os mesmos dados do bot.</p>
    </div>
  )
}
