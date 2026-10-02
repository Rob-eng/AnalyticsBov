import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api, fmtDay, fmtMm } from './api'
import BarChart from './BarChart'

const WATER = '#2A6FB0'

export default function RainSection({ propertyId }: { propertyId: number }) {
  const [enabled, setEnabled] = useState(false)
  const rain = useQuery({ queryKey: ['rain', propertyId], queryFn: () => api.rain(propertyId), enabled })
  useEffect(() => { setEnabled(false) }, [propertyId])
  const r = rain.data?.result

  return (
    <div className="block">
      <h3>Chuva</h3>
      {!enabled && (
        <>
          <p className="muted">Previsão de 7 dias, últimos 90 dias e comparação com a média de 10 anos.</p>
          <button className="btn btn-sm" onClick={() => setEnabled(true)}>Ver chuva</button>
        </>
      )}
      {rain.isFetching && <p className="muted">Buscando dados de chuva…</p>}
      {rain.isError && <p className="notice">{(rain.error as Error).message}</p>}
      {r && (
        <>
          <div className="kpis">
            <div><span className="kpi">{fmtMm(r.last30_mm)}</span><span className="muted small">últimos 30 dias</span></div>
            <div>
              <span className="kpi">{r.pct_of_normal != null ? `${r.pct_of_normal}%` : '—'}</span>
              <span className="muted small">da média ({fmtMm(r.normal30_mm)})</span>
            </div>
            <div><span className="kpi">{fmtMm(r.next7_mm)}</span><span className="muted small">próximos 7 dias</span></div>
          </div>
          {r.pct_of_normal != null && r.pct_of_normal < 60 && (
            <p className="notice">Chuva bem abaixo da média para esta época — atenção à oferta de pasto.</p>
          )}
          <p className="muted small">Próximos 7 dias</p>
          <BarChart color={WATER} unit="mm" ariaLabel="Chuva prevista para os próximos 7 dias"
            bars={r.forecast.map(d => ({ label: fmtDay(d.date), value: d.mm, tip: d.prob != null ? `chance de chuva ${d.prob}%` : '' }))} />
          <p className="muted small">Últimos 90 dias (por semana)</p>
          <BarChart color={WATER} unit="mm" ariaLabel="Chuva semanal dos últimos 90 dias"
            ref_={r.normal30_mm != null ? { value: (r.normal30_mm / 30) * 7, label: 'média semanal' } : undefined}
            bars={r.weeks.map(wk => ({ label: fmtDay(wk.end), value: wk.mm, tip: `semana de ${fmtDay(wk.start)} a ${fmtDay(wk.end)}` }))} />
        </>
      )}
    </div>
  )
}
