import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { api, fmtMonth, fmtNdvi, type Analysis, type Ndvi, type NdviMonth } from './api'
import NdviChart from './NdviChart'
import type { Pick } from './PropertyPanel'

type Props = { propertyId: number; shown: Ndvi | null; onShow: (n: Ndvi | null) => void; pick: Pick; setPick: (p: Pick) => void }

const pct = (from: number | null | undefined, to: number | null | undefined) =>
  from && to != null ? ((to - from) / from) * 100 : null
const fmtPct = (v: number | null) => v == null ? '—' : `${v >= 0 ? '+' : ''}${v.toFixed(0)}%`

const toOverlay = (a: Analysis<NdviMonth>, label: string): Ndvi => ({
  date: label, mean: a.result.mean, cloud_pct: null, image: a.file_url!, coordinates: a.result.coordinates,
})

export default function NdviSection({ propertyId, shown, onShow, pick, setPick }: Props) {
  const [enabled, setEnabled] = useState(false)
  const series = useQuery({ queryKey: ['ndvi-series', propertyId], queryFn: () => api.ndviSeries(propertyId, 24), enabled })
  const points = series.data?.result.series ?? []
  const withData = points.filter(p => p.mean != null)
  const [a, setA] = useState<string>('')
  const [b, setB] = useState<string>('')
  const [nextPick, setNextPick] = useState<'a' | 'b'>('a')

  // ponto de análise: clique no mapa → série NDVI só daquele ponto (raio de 15 m)
  const [picking, setPicking] = useState(false)
  const [point, setPoint] = useState<{ lat: number; lon: number } | null>(null)
  const zone = useQuery({
    queryKey: ['ndvi-zone', propertyId, point?.lat, point?.lon],
    queryFn: () => api.ndviZone(propertyId, { type: 'Point', coordinates: [point!.lon, point!.lat] }, 24),
    enabled: !!point, retry: false,
  })
  const zoneSeries = zone.data?.result.series ?? null
  useEffect(() => {
    if (picking && pick.point) { setPoint(pick.point); setPicking(false); setPick({ active: false, point: pick.point }) }
  }, [picking, pick.point, setPick])
  const startPicking = () => { setPicking(true); setPick({ active: true, point: null }) }
  const clearPoint = () => { setPoint(null); setPicking(false); setPick({ active: false, point: null }) }
  useEffect(() => () => setPick({ active: false, point: null }), [setPick])

  useEffect(() => { setEnabled(false); setA(''); setB(''); setPoint(null); setPicking(false) }, [propertyId])
  useEffect(() => {   // padrão: mesmo mês do ano anterior × mês mais recente com imagem
    if (!withData.length || a || b) return
    const last = withData[withData.length - 1].month
    const [y, m] = last.split('-')
    const prevYear = `${Number(y) - 1}-${m}`
    setB(last)
    setA(withData.some(p => p.month === prevYear) ? prevYear : withData[0].month)
  }, [withData, a, b])

  const compare = useMutation({ mutationFn: () => Promise.all([api.ndviMonth(propertyId, a), api.ndviMonth(propertyId, b)]) })
  const latest = useMutation({ mutationFn: () => api.ndvi(propertyId), onSuccess: onShow })
  const delta = useMemo(() => {
    const [ra, rb] = compare.data ?? []
    if (!ra?.result.mean || rb?.result.mean == null) return null
    return ((rb.result.mean - ra.result.mean) / ra.result.mean) * 100
  }, [compare.data])

  const pickMonth = (month: string) => {
    if (nextPick === 'a') setA(month); else setB(month)
    setNextPick(nextPick === 'a' ? 'b' : 'a')
    compare.reset()
  }

  return (
    <div className="block">
      <h3>Vigor da pastagem (NDVI)</h3>
      {!enabled && (
        <>
          <p className="muted">Histórico mês a mês dos últimos 24 meses (Sentinel-2, nuvens removidas).</p>
          <div className="row">
            <button className="btn btn-sm" onClick={() => setEnabled(true)}>Ver histórico</button>
            <button className="btn btn-sm btn-ghost" disabled={latest.isPending} onClick={() => latest.mutate()}>
              {latest.isPending ? 'Processando satélite…' : 'Última imagem'}
            </button>
          </div>
        </>
      )}
      {series.isFetching && <p className="muted">Calculando 24 meses de NDVI (≈15 s)…</p>}
      {series.isError && <p className="notice">{(series.error as Error).message}</p>}
      {latest.isError && <p className="notice">{(latest.error as Error).message}</p>}

      {series.isSuccess && (
        <>
          <p className="muted small">Linha: NDVI médio · faixa: 25%–75% dos pixels. Clique num mês para comparar.</p>
          <NdviChart series={points} selected={[a, b].filter(Boolean)} onPick={pickMonth} zone={zoneSeries} />

          <div className="row">
            {!point && !picking && <button className="btn btn-sm btn-ghost" onClick={startPicking}>Analisar um ponto</button>}
            {picking && <><span className="small muted">Clique no mapa, dentro do perímetro…</span><button className="link" onClick={clearPoint}>Cancelar</button></>}
            {point && <>
              <span className="small"><span className="swatch" style={{ background: '#2A6FB0' }} />Ponto {point.lat.toFixed(5)}, {point.lon.toFixed(5)}</span>
              <button className="link" onClick={startPicking}>Trocar</button>
              <button className="link" onClick={clearPoint}>Remover</button>
            </>}
          </div>
          {zone.isFetching && <p className="muted small">Calculando o NDVI do ponto (≈15 s)…</p>}
          {zone.isError && <p className="notice">{(zone.error as Error).message}</p>}
          <details className="table-toggle">
            <summary>Ver tabela</summary>
            <table className="mini-table">
              <thead><tr><th>Mês</th><th>NDVI</th><th>Faixa</th></tr></thead>
              <tbody>{[...points].reverse().map(p => (
                <tr key={p.month}><td>{fmtMonth(p.month)}</td><td>{fmtNdvi(p.mean)}</td><td>{p.mean == null ? 'sem imagem' : `${fmtNdvi(p.p25)}–${fmtNdvi(p.p75)}`}</td></tr>
              ))}</tbody>
            </table>
          </details>

          <div className="compare">
            <label className="field"><span>Mês A</span>
              <select className="input" value={a} onChange={e => { setA(e.target.value); compare.reset() }}>
                {withData.map(p => <option key={p.month} value={p.month}>{fmtMonth(p.month)}</option>)}
              </select>
            </label>
            <label className="field"><span>Mês B</span>
              <select className="input" value={b} onChange={e => { setB(e.target.value); compare.reset() }}>
                {withData.map(p => <option key={p.month} value={p.month}>{fmtMonth(p.month)}</option>)}
              </select>
            </label>
          </div>
          {zoneSeries && a && b && a !== b && (() => {
            const at = (s: typeof points, m: string) => s.find(p => p.month === m)?.mean ?? null
            const rows = [
              { name: 'Fazenda (média)', color: '#2E7D32', va: at(points, a), vb: at(points, b) },
              { name: 'Ponto', color: '#2A6FB0', va: at(zoneSeries, a), vb: at(zoneSeries, b) },
            ]
            return (
              <table className="zone-table">
                <thead><tr><th></th><th>{fmtMonth(a)}</th><th>{fmtMonth(b)}</th><th>Variação</th></tr></thead>
                <tbody>{rows.map(r => (
                  <tr key={r.name}>
                    <td><span className="swatch" style={{ background: r.color }} />{r.name}</td>
                    <td>{fmtNdvi(r.va)}</td><td>{fmtNdvi(r.vb)}</td><td>{fmtPct(pct(r.va, r.vb))}</td>
                  </tr>
                ))}</tbody>
              </table>
            )
          })()}
          <button className="btn btn-sm" disabled={!a || !b || a === b || compare.isPending} onClick={() => compare.mutate()}>
            {compare.isPending ? 'Gerando as duas imagens…' : 'Comparar'}
          </button>
          {compare.isError && <p className="notice">{(compare.error as Error).message}</p>}
          {compare.data && (
            <>
              <div className="compare-grid">
                {compare.data.map((r, k) => {
                  const label = fmtMonth(k ? b : a)
                  const active = shown?.image === r.file_url
                  return (
                    <button key={k} className={'thumb' + (active ? ' thumb-on' : '')} onClick={() => onShow(active ? null : toOverlay(r, label))}>
                      <img src={r.file_url!} alt={`NDVI de ${label}`} />
                      <span><strong>{label}</strong> · {fmtNdvi(r.result.mean)}</span>
                    </button>
                  )
                })}
              </div>
              {delta != null && (
                <p className={'delta ' + (delta >= 0 ? 'delta-up' : 'delta-down')}>
                  {delta >= 0 ? '▲' : '▼'} NDVI {delta >= 0 ? '+' : ''}{delta.toFixed(0)}% de {fmtMonth(a)} para {fmtMonth(b)}
                </p>
              )}
              <p className="muted small">Toque numa imagem para vê-la no mapa.</p>
            </>
          )}
        </>
      )}

      {shown && (
        <div className="row small muted">
          <span>No mapa: NDVI {shown.date.includes('-') ? shown.date.split('-').reverse().join('/') : shown.date} · média {fmtNdvi(shown.mean)}</span>
          <button className="link" onClick={() => onShow(null)}>Ocultar</button>
        </div>
      )}
    </div>
  )
}
