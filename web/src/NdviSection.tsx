import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { api, fmtMonth, fmtNdvi, type Analysis, type Ndvi, type NdviMonth } from './api'
import NdviChart from './NdviChart'

type Props = { propertyId: number; shown: Ndvi | null; onShow: (n: Ndvi | null) => void }

const toOverlay = (a: Analysis<NdviMonth>, label: string): Ndvi => ({
  date: label, mean: a.result.mean, cloud_pct: null, image: a.file_url!, coordinates: a.result.coordinates,
})

export default function NdviSection({ propertyId, shown, onShow }: Props) {
  const [enabled, setEnabled] = useState(false)
  const series = useQuery({ queryKey: ['ndvi-series', propertyId], queryFn: () => api.ndviSeries(propertyId, 24), enabled })
  const points = series.data?.result.series ?? []
  const withData = points.filter(p => p.mean != null)
  const [a, setA] = useState<string>('')
  const [b, setB] = useState<string>('')
  const [nextPick, setNextPick] = useState<'a' | 'b'>('a')

  useEffect(() => { setEnabled(false); setA(''); setB('') }, [propertyId])
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

  const pick = (month: string) => {
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
          <NdviChart series={points} selected={[a, b].filter(Boolean)} onPick={pick} />
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
