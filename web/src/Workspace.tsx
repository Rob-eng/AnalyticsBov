import { useCallback, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, Route, Routes, useMatch, useNavigate, useSearchParams } from 'react-router'
import { api, fmtHa, PLAN_LABEL, type Me } from './api'
import MapView, { type Focus } from './MapView'
import PropertyPanel from './PropertyPanel'
import AddProperty from './AddProperty'
import MarketBoard from './MarketBoard'

export default function Workspace({ me }: { me: Me }) {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const props = useQuery({ queryKey: ['properties'], queryFn: api.properties })
  // chave sob 'properties': criar/excluir/vincular CAR já invalida os perímetros junto
  const perimeters = useQuery({ queryKey: ['properties', 'perimeters'], queryFn: api.perimeters })
  const [mode, setMode] = useState<Me['mode']>(me.mode)
  const [focus, setFocus] = useState<Focus | null>(null)
  const [pick, setPick] = useState<{ active: boolean; point: { lat: number; lon: number } | null }>({ active: false, point: null })
  const openMatch = useMatch('/p/:id')
  const marketMatch = useMatch('/mercado')
  const [params, setParams] = useSearchParams()
  const selectedId = openMatch ? Number(openMatch.params.id) : null
  const hasConsultancy = me.organizations.some(o => o.kind === 'consultoria')
  const list = props.data ?? []
  // praça do mercado: ?uf= na URL; padrão = UF da primeira propriedade (ou MS)
  const marketUf = params.get('uf') || list.find(p => p.uf)?.uf || 'MS'
  const setMarketUf = (uf: string) => setParams({ uf }, { replace: true })

  const onPick = useCallback((lat: number, lon: number) => {
    setPick(p => (p.active ? { ...p, point: { lat, lon } } : p))
  }, [])
  const onSelect = useCallback((id: number) => navigate(`/p/${id}`), [navigate])

  async function logout() {
    await api.logout()
    qc.clear()
    window.location.href = '/app/'
  }

  return (
    <div className="workspace">
      <aside className="rail">
        <header className="rail-head">
          <div className="brand-row">
            <Link to="/" className="brand">Agro Analytics</Link>
            <Link to="/mercado" className="rail-link" aria-current={marketMatch ? 'page' : undefined}>Mercado</Link>
          </div>
          <div className="mode" role="tablist" aria-label="Modo de uso">
            <button role="tab" aria-selected={mode === 'produtor'} onClick={() => setMode('produtor')}>Minhas fazendas</button>
            <button role="tab" aria-selected={mode === 'consultor'} onClick={() => setMode('consultor')}>Carteira de clientes</button>
          </div>
        </header>

        {mode === 'consultor' && !hasConsultancy ? (
          <section className="panel">
            <h2>Carteira de clientes</h2>
            <p>Atenda várias fazendas de clientes em um só lugar: indicadores lado a lado, alertas e documentos vencendo.</p>
            <p className="muted">Disponível no plano Ouro. Em breve nesta tela.</p>
          </section>
        ) : (
          <Routes>
            <Route path="/p/:id" element={<PropertyPanel onFocus={setFocus} pick={pick} setPick={setPick} />} />
            <Route path="/nova" element={<AddProperty pick={pick} setPick={setPick} />} />
            <Route path="/mercado" element={
              <section className="panel">
                <Link className="link back" to="/">← Propriedades</Link>
                <h2>Mercado do boi</h2>
                <p className="muted">Cotações da praça, curva projetada da B3, preços do mundo e reposição nos leilões, com os mesmos dados do bot.</p>
                {list.some(p => p.uf) && (
                  <div className="block">
                    <h3>Praças das suas fazendas</h3>
                    <div className="row">{[...new Set(list.map(p => p.uf).filter(Boolean))].map(uf => (
                      <button key={uf} className={'btn btn-sm' + (uf === marketUf ? '' : ' btn-ghost')} onClick={() => setMarketUf(uf!)}>{uf}</button>
                    ))}</div>
                  </div>
                )}
                <p className="muted small">O valor estimado do rebanho de cada fazenda fica na aba Rebanho da propriedade.</p>
              </section>
            } />
            <Route path="*" element={
              <section className="panel">
                <div className="panel-title">
                  <h2>{list.length ? `${list.length} propriedade${list.length > 1 ? 's' : ''}` : 'Propriedades'}</h2>
                  <Link className="btn btn-sm" to="/nova">Adicionar</Link>
                </div>
                {props.isPending && <p className="muted">Carregando propriedades…</p>}
                {props.isError && <p className="notice">Não foi possível carregar as propriedades. <button className="link" onClick={() => props.refetch()}>Tentar de novo</button></p>}
                {props.isSuccess && !list.length && (
                  <div className="empty-box">
                    <p>Você ainda não tem propriedades.</p>
                    <p className="muted">Adicione pelo código do CAR ou clicando na fazenda no mapa. As cadastradas no bot aparecem aqui também.</p>
                  </div>
                )}
                <ul className="prop-list">
                  {list.map(p => (
                    <li key={p.id}>
                      <Link className="prop" to={`/p/${p.id}`}>
                        <span className="prop-name">{p.name}</span>
                        <span className="prop-meta">{p.has_perimeter ? `${fmtHa(p.area_ha)} · ${p.municipio ?? ''}${p.uf ? '/' + p.uf : ''}` : 'Sem CAR vinculado'}</span>
                      </Link>
                    </li>
                  ))}
                </ul>
              </section>
            } />
          </Routes>
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
        <MapView
          properties={list}
          perimeters={perimeters.data ?? null}
          selectedId={selectedId}
          onSelect={onSelect}
          focus={selectedId ? focus : null}
          pickMode={pick.active}
          picked={pick.point}
          onPick={onPick}
        />
        {marketMatch && <div className="market-stage"><MarketBoard uf={marketUf} onUf={setMarketUf} /></div>}
        {focus?.drawing && selectedId && <div className="map-hint" role="status">Clique para marcar os cantos · clique no primeiro ponto para fechar</div>}
        {pick.active && <div className="map-hint" role="status">{selectedId ? 'Clique no ponto da fazenda que quer analisar' : 'Clique dentro da fazenda no mapa'}</div>}
      </main>
    </div>
  )
}
