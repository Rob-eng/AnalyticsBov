import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, type Alerts, type Me, type PropertyDetail } from './api'

const ITEMS: { key: keyof Alerts; title: string; text: string; needsCar?: boolean }[] = [
  { key: 'ndvi', title: 'Nova imagem de satélite', text: 'Quando sair uma imagem Sentinel-2 sem nuvens da fazenda, com o NDVI do dia.' },
  { key: 'rain', title: 'Chuva abaixo da média', text: 'Verificado toda segunda: avisa se os últimos 30 dias tiveram menos da metade da chuva normal para a época.' },
  { key: 'prodes', title: 'Novo desmatamento (PRODES)', text: 'Verificado todo mês: avisa se o INPE publicar um apontamento novo que cruze o perímetro.', needsCar: true },
]

export default function AlertsSection({ property }: { property: PropertyDetail }) {
  const qc = useQueryClient()
  const me = qc.getQueryData<Me>(['me'])
  const channel = me?.platform === 'whatsapp' ? 'no seu WhatsApp' : 'no seu Telegram'
  // estado local: o interruptor muda na hora; a resposta do servidor confirma (ou desfaz, se falhar)
  const [alerts, setAlerts] = useState<Alerts>(property.alerts)
  useEffect(() => { setAlerts(property.alerts) }, [property.id, property.alerts])
  const save = useMutation({
    mutationFn: (a: Partial<Alerts>) => api.setAlerts(property.id, a),
    onMutate: a => { const prev = alerts; setAlerts({ ...alerts, ...a }); return prev },
    onSuccess: saved => { setAlerts(saved); qc.invalidateQueries({ queryKey: ['property', property.id] }) },
    onError: (_e, _a, prev) => { if (prev) setAlerts(prev) },
  })
  useQuery({ queryKey: ['me'], queryFn: api.me, enabled: !me })

  return (
    <div className="block">
      <h3>Alertas</h3>
      <p className="muted small">Os avisos chegam {channel}, com o link para esta página.</p>
      <ul className="alert-list">
        {ITEMS.map(it => {
          const blocked = it.needsCar && !property.has_perimeter
          const on = alerts[it.key]
          return (
            <li key={it.key}>
              <label className={'alert-item' + (blocked ? ' alert-off' : '')}>
                <span className="alert-text">
                  <strong>{it.title}</strong>
                  <span className="muted small">{blocked ? 'Vincule o CAR para usar este alerta.' : it.text}</span>
                </span>
                <input type="checkbox" role="switch" className="switch" checked={on && !blocked} disabled={blocked || save.isPending}
                  onChange={e => save.mutate({ [it.key]: e.target.checked })} aria-label={it.title} />
              </label>
            </li>
          )
        })}
      </ul>
      {save.isError && <p className="notice">{(save.error as Error).message}</p>}
    </div>
  )
}
