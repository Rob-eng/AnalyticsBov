import type * as GeoJSON from 'geojson'
import { useEffect, useRef, useState } from 'react'
import * as maplibregl from 'maplibre-gl'
// MapLibre 6: o worker é um módulo à parte; o Vite empacota com as dependências (?worker&url)
import { TerraDraw, TerraDrawPolygonMode, TerraDrawSelectMode } from 'terra-draw'
import { TerraDrawMapLibreGLAdapter } from 'terra-draw-maplibre-gl-adapter'
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url'
import { LAYER_ORDER, LAYER_STYLE, type Ndvi, type Property } from './api'

maplibregl.setWorkerUrl(workerUrl)

// Base de satélite: Esri World Imagery (conferir licença comercial antes do lançamento)
const SATELLITE_STYLE: maplibregl.StyleSpecification = {
  version: 8,
  sources: {
    sat: {
      type: 'raster',
      tiles: ['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'],
      tileSize: 256, maxzoom: 18,
      attribution: 'Imagens © Esri, Maxar, Earthstar Geographics',
    },
  },
  layers: [{ id: 'sat', type: 'raster', source: 'sat' }],
}
const EMPTY: GeoJSON.FeatureCollection = { type: 'FeatureCollection', features: [] }
const IPE = '#E8B730'
const TINTA = '#17251C'

export type Focus = {
  perimeter: GeoJSON.MultiPolygon | null
  bbox: [number, number, number, number] | null
  layers: GeoJSON.FeatureCollection | null
  visible: Set<string>
  ndvi: Ndvi | null
  prodes?: GeoJSON.FeatureCollection | null
  prodesSelected?: Set<string>
  // piquetes: properties {id, name, area_ha, ndvi?}; id -1 = desenhado e ainda não salvo
  paddocks?: GeoJSON.FeatureCollection | null
  paddockSelected?: number | null
  paddockExclusions?: GeoJSON.FeatureCollection | null   // áreas suprimidas (mata, água) — fora do pasto
  drawing?: boolean
  onDrawn?: (g: GeoJSON.Polygon) => void
  onPaddockClick?: (id: number) => void
  // edição do formato de um piquete (vértices arrastáveis); onEdited recebe a geometria a cada mudança
  editing?: { id: number; geometry: GeoJSON.Polygon } | null
  onEdited?: (g: GeoJSON.Polygon) => void
}

// mesma escala do NDVI em imagem (0 a 0,8), para as cores dos piquetes significarem o mesmo
const NDVI_FILL: maplibregl.ExpressionSpecification = ['interpolate', ['linear'], ['get', 'ndvi'],
  0, '#d7191c', 0.2, '#fdae61', 0.4, '#ffffbf', 0.6, '#a6d96a', 0.8, '#1a9641']

// boizinho minimalista (cabeça de frente com chifres), no traço da interface
const STEER_SVG = '<svg class="steer" viewBox="0 0 24 24" width="15" height="15" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">'
  + '<path d="M3.5 5.5c.8 2.3 2.8 3.3 5 3.2"/><path d="M20.5 5.5c-.8 2.3-2.8 3.3-5 3.2"/>'
  + '<path d="M5.2 10.4 8 9.6M18.8 10.4 16 9.6"/>'
  + '<path d="M8 8.7h8l-1 6.6c-.3 2.1-1.6 3.6-3 3.6s-2.7-1.5-3-3.6z"/>'
  + '<path d="M10.6 16.6h.01M13.4 16.6h.01" stroke-width="2.4"/></svg>'

const ringCenter = (g: GeoJSON.Polygon): [number, number] => {
  const ring = g.coordinates[0].slice(0, -1)
  return [ring.reduce((s, c) => s + c[0], 0) / ring.length, ring.reduce((s, c) => s + c[1], 0) / ring.length]
}

type Props = {
  properties: Property[]
  perimeters?: GeoJSON.FeatureCollection | null
  selectedId?: number | null
  onSelect?: (id: number) => void
  focus?: Focus | null
  pickMode?: boolean
  picked?: { lat: number; lon: number } | null
  onPick?: (lat: number, lon: number) => void
  interactive?: boolean
}

export default function MapView({ properties, perimeters, selectedId, onSelect, focus, pickMode, picked, onPick, interactive = true }: Props) {
  const container = useRef<HTMLDivElement>(null)
  const map = useRef<maplibregl.Map | null>(null)
  const markers = useRef<maplibregl.Marker[]>([])
  const pickMarker = useRef<maplibregl.Marker | null>(null)
  const [ready, setReady] = useState(false)
  const onPickRef = useRef(onPick)
  onPickRef.current = onPick
  const onSelectRef = useRef(onSelect)
  onSelectRef.current = onSelect
  const pickRef = useRef(pickMode)
  pickRef.current = pickMode
  const focusRef = useRef(focus)
  focusRef.current = focus
  const draw = useRef<TerraDraw | null>(null)
  const editId = useRef<string | number | null>(null)
  const paddockMarkers = useRef<maplibregl.Marker[]>([])

  // criação do mapa + fontes/camadas vazias (preenchidas depois com setData)
  useEffect(() => {
    if (!container.current) return
    const m = new maplibregl.Map({
      container: container.current, style: SATELLITE_STYLE,
      center: [-54.6, -20.4], zoom: interactive ? 5.5 : 6.2, interactive,
      attributionControl: { compact: true },
    })
    if (interactive) {
      m.addControl(new maplibregl.NavigationControl({ visualizePitch: false }), 'top-right')
      m.addControl(new maplibregl.ScaleControl({ unit: 'metric' }), 'bottom-right')
    }
    m.on('load', () => {
      m.addSource('car', { type: 'geojson', data: EMPTY })
      m.addSource('perimeter', { type: 'geojson', data: EMPTY })
      for (const cat of LAYER_ORDER) {
        const st = LAYER_STYLE[cat]
        m.addLayer({ id: `car-${cat}-fill`, type: 'fill', source: 'car', filter: ['==', ['get', 'category'], cat],
          paint: { 'fill-color': st.color, 'fill-opacity': st.opacity } })
        m.addLayer({ id: `car-${cat}-line`, type: 'line', source: 'car', filter: ['==', ['get', 'category'], cat],
          paint: { 'line-color': st.color, 'line-width': cat === 'agua' ? 2 : 0.8 } })
      }
      // PRODES: azul até 2008 (marco legal 22/07/2008), vermelho depois
      m.addSource('prodes', { type: 'geojson', data: EMPTY })
      const prodesColor: maplibregl.ExpressionSpecification = ['case', ['<=', ['coalesce', ['get', 'year'], 0], 2008], '#2b83ba', '#d7191c']
      m.addLayer({ id: 'prodes-fill', type: 'fill', source: 'prodes', paint: { 'fill-color': prodesColor, 'fill-opacity': ['case', ['boolean', ['get', 'selected'], false], 0.65, 0.35] } })
      m.addLayer({ id: 'prodes-line', type: 'line', source: 'prodes', paint: { 'line-color': prodesColor, 'line-width': ['case', ['boolean', ['get', 'selected'], false], 3, 1.5] } })
      // mapa geral: perímetro de cada propriedade com CAR (clique abre a propriedade)
      m.addSource('overview', { type: 'geojson', data: EMPTY })
      m.addLayer({ id: 'overview-fill', type: 'fill', source: 'overview', paint: { 'fill-color': IPE, 'fill-opacity': 0.12 } })
      m.addLayer({ id: 'overview-halo', type: 'line', source: 'overview', paint: { 'line-color': TINTA, 'line-width': 4, 'line-opacity': 0.6 } })
      m.addLayer({ id: 'overview-line', type: 'line', source: 'overview', paint: { 'line-color': IPE, 'line-width': 2 } })
      m.on('click', 'overview-fill', e => {
        const id = e.features?.[0]?.properties?.id
        if (id != null && !pickRef.current) onSelectRef.current?.(Number(id))
      })
      m.on('mouseenter', 'overview-fill', () => { if (!pickRef.current) m.getCanvas().style.cursor = 'pointer' })
      m.on('mouseleave', 'overview-fill', () => { if (!pickRef.current) m.getCanvas().style.cursor = '' })
      m.addSource('paddocks', { type: 'geojson', data: EMPTY })
      m.addLayer({ id: 'paddock-fill', type: 'fill', source: 'paddocks', paint: {
        // NDVI (quando pedido) > situação do pastejo > neutro
        'fill-color': ['case', ['has', 'ndvi'], NDVI_FILL, ['has', 'status'], ['match', ['get', 'status'],
          'em_uso', '#E8B730', 'pronto', '#1a9641', 'descanso', '#9aa59c', 'descanso_longo', '#2A6FB0', IPE], IPE],
        'fill-opacity': ['case', ['has', 'ndvi'], 0.6, ['==', ['get', 'id'], -1], 0.3,
          ['all', ['has', 'status'], ['!=', ['get', 'status'], 'sem_registro']], 0.45, 0.12] } })
      m.addLayer({ id: 'paddock-line', type: 'line', source: 'paddocks', paint: {
        'line-color': ['case', ['boolean', ['get', 'selected'], false], IPE, '#ffffff'],
        'line-width': ['case', ['boolean', ['get', 'selected'], false], 3.5, 1.6],
        'line-dasharray': ['case', ['==', ['get', 'id'], -1], ['literal', [2, 1.5]], ['literal', [1, 0]]] } })
      m.addSource('paddock-excl', { type: 'geojson', data: EMPTY })
      m.addLayer({ id: 'paddock-excl-fill', type: 'fill', source: 'paddock-excl', paint: { 'fill-color': TINTA, 'fill-opacity': 0.55 } })
      m.addLayer({ id: 'paddock-excl-line', type: 'line', source: 'paddock-excl', paint: { 'line-color': '#ffffff', 'line-width': 1.2, 'line-dasharray': [2, 2] } })
      m.on('click', 'paddock-fill', e => {
        const id = Number(e.features?.[0]?.properties?.id)
        if (id > 0 && !focusRef.current?.drawing && !pickRef.current) focusRef.current?.onPaddockClick?.(id)
      })
      m.addLayer({ id: 'perimeter-halo', type: 'line', source: 'perimeter', paint: { 'line-color': TINTA, 'line-width': 5 } })
      m.addLayer({ id: 'perimeter-line', type: 'line', source: 'perimeter', paint: { 'line-color': IPE, 'line-width': 2.5 } })
      // desenho de piquetes (Terra Draw): só fica ativo enquanto focus.drawing
      const td = new TerraDraw({
        adapter: new TerraDrawMapLibreGLAdapter({ map: m }),
        modes: [new TerraDrawPolygonMode({ styles: {
          fillColor: '#E8B730', fillOpacity: 0.25, outlineColor: '#E8B730', outlineWidth: 2.5,
          closingPointColor: '#17251C', closingPointWidth: 6, closingPointOutlineColor: '#ffffff', closingPointOutlineWidth: 2,
        } }), new TerraDrawSelectMode({
          flags: { polygon: { feature: { draggable: true, coordinates: { midpoints: true, draggable: true, deletable: true } } } },
          styles: { selectedPolygonColor: '#E8B730', selectedPolygonFillOpacity: 0.25, selectedPolygonOutlineColor: '#E8B730',
                    selectedPolygonOutlineWidth: 2.5, selectionPointColor: '#17251C', selectionPointWidth: 6,
                    selectionPointOutlineColor: '#ffffff', selectionPointOutlineWidth: 2, midPointColor: '#E8B730', midPointWidth: 4 },
        })],
      })
      td.on('change', ids => {
        const eid = editId.current
        if (eid == null || !ids.includes(eid) || !td.hasFeature(eid)) return
        const f = td.getSnapshotFeature(eid)
        if (f?.geometry.type === 'Polygon') focusRef.current?.onEdited?.(f.geometry as GeoJSON.Polygon)
      })
      td.on('finish', id => {
        if (editId.current != null) return   // 'finish' do arraste na edição não é piquete novo
        const f = td.getSnapshotFeature(id)
        td.clear()
        if (f?.geometry.type === 'Polygon') focusRef.current?.onDrawn?.(f.geometry as GeoJSON.Polygon)
      })
      draw.current = td
      setReady(true)
    })
    m.on('click', e => onPickRef.current?.(e.lngLat.lat, e.lngLat.lng))
    // gancho do teste de ponta a ponta (e2e/smoke.mjs): centraliza o mapa num ponto
    const qaFly = (ev: Event) => { const { lat, lon } = (ev as CustomEvent).detail; m.jumpTo({ center: [lon, lat], zoom: 14 }) }
    window.addEventListener('qa-fly', qaFly)
    m.once('remove', () => window.removeEventListener('qa-fly', qaFly))
    map.current = m
    return () => { try { draw.current?.stop() } catch { /* mapa já removido */ } draw.current = null; m.remove(); map.current = null; setReady(false) }
  }, [interactive])

  useEffect(() => {
    if (map.current) map.current.getCanvas().style.cursor = pickMode ? 'crosshair' : ''
  }, [pickMode])

  // pinos das propriedades (escondidos quando uma propriedade está aberta)
  useEffect(() => {
    const m = map.current
    if (!m) return
    markers.current.forEach(mk => mk.remove())
    markers.current = focus ? [] : properties.filter(p => p.lat != null && p.lon != null).map(p => {
      const el = document.createElement('button')
      el.className = 'pin' + (p.id === selectedId ? ' pin-active' : '')
      el.type = 'button'
      el.setAttribute('aria-label', p.name)
      el.innerHTML = `<span class="pin-dot"></span><span class="pin-label">${p.name.replace(/</g, '&lt;')}</span>`
      el.addEventListener('click', ev => { ev.stopPropagation(); onSelect?.(p.id) })
      return new maplibregl.Marker({ element: el, anchor: 'left' }).setLngLat([p.lon!, p.lat!]).addTo(m)
    })
    const overview = m.getSource('overview') as maplibregl.GeoJSONSource | undefined
    overview?.setData(!focus && perimeters ? perimeters : EMPTY)
    const pts = properties.filter(p => p.lat != null)
    if (!focus && pts.length && interactive && !pickMode) {
      const b = new maplibregl.LngLatBounds()
      pts.forEach(p => b.extend([p.lon!, p.lat!]))
      const walk = (c: unknown): void => {
        if (Array.isArray(c) && typeof c[0] === 'number') b.extend(c as [number, number]); else if (Array.isArray(c)) c.forEach(walk)
      }
      perimeters?.features.forEach(f => walk((f.geometry as GeoJSON.Polygon).coordinates))
      m.fitBounds(b, { padding: 90, maxZoom: 12, duration: 600 })
    }
  }, [properties, perimeters, selectedId, onSelect, interactive, focus, pickMode, ready])

  // propriedade aberta: perímetro + camadas do CAR + NDVI
  useEffect(() => {
    const m = map.current
    if (!m || !ready) return
    ;(m.getSource('perimeter') as maplibregl.GeoJSONSource).setData(
      focus?.perimeter ? { type: 'Feature', geometry: focus.perimeter, properties: {} } : EMPTY)
    ;(m.getSource('car') as maplibregl.GeoJSONSource).setData(focus?.layers ?? EMPTY)
    ;(m.getSource('prodes') as maplibregl.GeoJSONSource).setData(focus?.prodes ? {
      ...focus.prodes,
      features: focus.prodes.features.map(f => ({ ...f, properties: { ...f.properties, selected: focus.prodesSelected?.has(f.properties?.uuid) ?? false } })),
    } : EMPTY)
    ;(m.getSource('paddocks') as maplibregl.GeoJSONSource).setData(focus?.paddocks ? {
      ...focus.paddocks,
      features: focus.paddocks.features.map(f => ({ ...f, properties: { ...f.properties, selected: f.properties?.id === focus.paddockSelected } })),
    } : EMPTY)
    ;(m.getSource('paddock-excl') as maplibregl.GeoJSONSource).setData(focus?.paddockExclusions ?? EMPTY)
    // nomes dos piquetes (o estilo de satélite não tem fontes para rótulos no próprio mapa)
    paddockMarkers.current.forEach(mk => mk.remove())
    paddockMarkers.current = (focus?.paddocks?.features ?? []).filter(f => f.properties?.id > 0).map(f => {
      const el = document.createElement('div')
      el.className = 'paddock-label' + (f.properties!.id === focus?.paddockSelected ? ' paddock-label-on' : '')
      const pr = f.properties!
      const nd = pr.ndvi
      const name = document.createElement('span')
      name.textContent = pr.name + (typeof nd === 'number' ? ` · ${nd.toFixed(2).replace('.', ',')}` : '')
      el.append(name)
      if (pr.in_use) {
        const use = document.createElement('span')
        use.className = 'paddock-use'
        use.innerHTML = STEER_SVG
        use.append(typeof pr.ua_ha === 'number' ? `${pr.ua_ha.toFixed(2).replace('.', ',')} UA/ha` : 'em uso')
        el.append(use)
        el.title = `Em uso · ${use.textContent}`
      }
      return new maplibregl.Marker({ element: el }).setLngLat(ringCenter(f.geometry as GeoJSON.Polygon)).addTo(m)
    })
    // com NDVI, PRODES ou piquetes na tela, as camadas do CAR viram só contorno para não esconder o que importa
    const outlineOnly = !!focus?.ndvi || !!focus?.prodes?.features.length || !!focus?.paddocks?.features.length || !!focus?.editing
    for (const cat of LAYER_ORDER) {
      const vis = focus?.visible.has(cat) ? 'visible' : 'none'
      m.setLayoutProperty(`car-${cat}-fill`, 'visibility', outlineOnly ? 'none' : vis)
      m.setLayoutProperty(`car-${cat}-line`, 'visibility', vis)
      m.setPaintProperty(`car-${cat}-line`, 'line-width', focus?.ndvi ? 1.6 : cat === 'agua' ? 2 : 0.8)
    }
    if (m.getLayer('ndvi')) m.removeLayer('ndvi')
    if (m.getSource('ndvi')) m.removeSource('ndvi')
    if (focus?.ndvi) {
      m.addSource('ndvi', { type: 'image', url: focus.ndvi.image, coordinates: focus.ndvi.coordinates as [[number, number], [number, number], [number, number], [number, number]] })
      m.addLayer({ id: 'ndvi', type: 'raster', source: 'ndvi', paint: { 'raster-opacity': 0.85 } }, 'car-sem_classificacao-fill')
    }
  }, [focus, ready])

  // liga/desliga o desenho (piquete novo) e a edição de formato (piquete existente)
  const editingId = focus?.editing?.id ?? null
  useEffect(() => {
    const td = draw.current
    if (!td || !ready) return
    const ed = focusRef.current?.editing
    if (td.enabled) td.clear()
    editId.current = null
    if (focus?.drawing) {
      if (!td.enabled) td.start()
      td.setMode('polygon')
    } else if (ed) {
      if (!td.enabled) td.start()
      const fid = td.getFeatureId()
      td.addFeatures([{ type: 'Feature', id: fid, geometry: ed.geometry, properties: { mode: 'polygon' } }])
      td.setMode('select')
      editId.current = fid
      td.selectFeature(fid)
    } else if (td.enabled) {
      td.stop()
    }
  }, [focus?.drawing, editingId, ready])

  // enquadra a propriedade aberta
  useEffect(() => {
    if (map.current && focus?.bbox) {
      const [x0, y0, x1, y1] = focus.bbox
      map.current.fitBounds([[x0, y0], [x1, y1]], { padding: { top: 60, bottom: 60, left: 60, right: 60 }, duration: 800 })
    }
  }, [focus?.bbox])

  // ponto escolhido no modo cadastro
  useEffect(() => {
    pickMarker.current?.remove()
    pickMarker.current = null
    if (picked && map.current) {
      const el = document.createElement('div')
      el.className = 'pick-marker'
      pickMarker.current = new maplibregl.Marker({ element: el }).setLngLat([picked.lon, picked.lat]).addTo(map.current)
    }
  }, [picked])

  return <div ref={container} className="map" />
}
