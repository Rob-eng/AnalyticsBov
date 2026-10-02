import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api, PLAN_LABEL, type Me } from './api'
import MapView from './MapView'

export default function Workspace({ me }: { me: Me }) {
  const qc = useQueryClient()
  const props = useQuery({ queryKey: ['properties'], queryFn: api.properties })
  const [selected, setSelected] = useState<number | null>(null)
  const [mode, setMode] = useState<Me['mode']>(me.mode)
  const hasConsultancy = me.organizations.some(o => o.kind === 'consultoria')

  async function logout() {
    await api.logout()
    qc.clear()
    window.location.reload()
  }

  const list = props.data ?? []
  const current = list.find(p => p.id === selected)

  return (
    <div className="workspace">
      <aside className="rail">
        <header className="rail-head">
          <p className="brand">Agro Analytics</p>
          <div className="mode" role="tablist" aria-label="Modo de uso">
            <button role="tab" aria-selected={mode === 'produtor'} onClick={() => setMode('produtor')}>Minhas fazendas</button>
            <button role="tab" aria-selected={mode === 'consultor'} onClick={() => setMode('consultor')}>Carteira de clientes</button>
          </div>
        </header>

        {mode === 'consultor' && !hasConsultancy ? (
          <section className="empty">
            <h2>Carteira de clientes</h2>
            <p>Atenda várias fazendas de clientes em um só lugar: indicadores lado a lado, alertas e documentos vencendo.</p>
            <p className="muted">Disponível no plano Ouro. Em breve nesta tela.</p>
          </section>
        ) : (
          <section className="props">
            <h2>{list.length ? `${list.length} propriedade${list.length > 1 ? 's' : ''}` : 'Propriedades'}</h2>
            {props.isPending && <p className="muted">Carregando propriedades…</p>}
            {props.isError && <p className="notice">Não foi possível carregar as propriedades. <button className="link" onClick={() => props.refetch()}>Tentar de novo</button></p>}
            {props.isSuccess && !list.length && (
              <div className="empty">
                <p>Você ainda não tem propriedades cadastradas.</p>
                <p className="muted">Cadastre pelo bot com "cadastrar propriedade" — elas aparecem aqui na hora. O cadastro pela web chega na próxima etapa.</p>
              </div>
            )}
            <ul>
              {list.map(p => (
                <li key={p.id}>
                  <button className={'prop' + (p.id === selected ? ' prop-active' : '')} onClick={() => setSelected(p.id)}>
                    <span className="prop-name">{p.name}</span>
                    <span className="prop-coord">{p.lat.toFixed(4)}, {p.lon.toFixed(4)}</span>
                  </button>
                </li>
              ))}
            </ul>
          </section>
        )}

        <footer className="rail-foot">
          <div>
            <p className="who">{me.name || me.chat_id}</p>
            <p className="muted">Plano {PLAN_LABEL[me.plan]} · {me.platform === 'whatsapp' ? 'WhatsApp' : 'Telegram'}</p>
          </div>
          <button className="link" onClick={logout}>Sair</button>
        </footer>
      </aside>

      <main className="stage">
        <MapView properties={list} selectedId={selected} onSelect={setSelected} />
        {current && (
          <div className="sheet" role="dialog" aria-label={current.name}>
            <h3>{current.name}</h3>
            <p className="prop-coord">{current.lat.toFixed(5)}, {current.lon.toFixed(5)}</p>
            <p className="muted">Mapa CAR, NDVI e histórico desta fazenda chegam na próxima etapa.</p>
            <button className="link" onClick={() => setSelected(null)}>Fechar</button>
          </div>
        )}
      </main>
    </div>
  )
}
