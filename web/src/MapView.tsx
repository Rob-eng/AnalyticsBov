import type * as GeoJSON from 'geojson'
import { useEffect, useRef, useState } from 'react'
import * as maplibregl from 'maplibre-gl'
// MapLibre 6: o worker é um módulo à parte; o Vite empacota com as dependências (?worker&url)
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
      m.addLayer({ id: 'perimeter-halo', type: 'line', source: 'perimeter', paint: { 'line-color': TINTA, 'line-width': 5 } })
      m.addLayer({ id: 'perimeter-line', type: 'line', source: 'perimeter', paint: { 'line-color': IPE, 'line-width': 2.5 } })
      setReady(true)
    })
    m.on('click', e => onPickRef.current?.(e.lngLat.lat, e.lngLat.lng))
    // gancho do teste de ponta a ponta (e2e/smoke.mjs): centraliza o mapa num ponto
    const qaFly = (ev: Event) => { const { lat, lon } = (ev as CustomEvent).detail; m.jumpTo({ center: [lon, lat], zoom: 14 }) }
    window.addEventListener('qa-fly', qaFly)
    m.once('remove', () => window.removeEventListener('qa-fly', qaFly))
    map.current = m
    return () => { m.remove(); map.current = null; setReady(false) }
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
    // com NDVI ou PRODES na tela, as camadas do CAR viram só contorno para não esconder o que importa
    const outlineOnly = !!focus?.ndvi || !!focus?.prodes?.features.length
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
