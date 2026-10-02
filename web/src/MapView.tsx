import { useEffect, useRef } from 'react'
import * as maplibregl from 'maplibre-gl'
// MapLibre 6: o worker é um módulo à parte; o Vite empacota com as dependências (?worker&url)
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url'
type MLMap = maplibregl.Map

maplibregl.setWorkerUrl(workerUrl)
import type { Property } from './api'

// Base de satélite: Esri World Imagery (conferir licença comercial antes do lançamento — ver plano).
const SATELLITE_STYLE: maplibregl.StyleSpecification = {
  version: 8,
  sources: {
    sat: {
      type: 'raster',
      tiles: ['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'],
      tileSize: 256,
      maxzoom: 18,
      attribution: 'Imagens © Esri, Maxar, Earthstar Geographics',
    },
  },
  layers: [{ id: 'sat', type: 'raster', source: 'sat' }],
}

type Props = {
  properties: Property[]
  selectedId?: number | null
  onSelect?: (id: number) => void
  interactive?: boolean
}

export default function MapView({ properties, selectedId, onSelect, interactive = true }: Props) {
  const container = useRef<HTMLDivElement>(null)
  const map = useRef<MLMap | null>(null)
  const markers = useRef<maplibregl.Marker[]>([])

  useEffect(() => {
    if (!container.current) return
    const m = new maplibregl.Map({
      container: container.current,
      style: SATELLITE_STYLE,
      center: [-54.6, -20.4],   // MS
      zoom: interactive ? 5.5 : 6.2,
      interactive,
      attributionControl: { compact: true },
    })
    if (interactive) m.addControl(new maplibregl.NavigationControl({ visualizePitch: false }), 'top-right')
    map.current = m
    return () => { m.remove(); map.current = null }
  }, [interactive])

  // marcadores das propriedades
  useEffect(() => {
    const m = map.current
    if (!m) return
    markers.current.forEach(mk => mk.remove())
    markers.current = properties.map(p => {
      const el = document.createElement('button')
      el.className = 'pin' + (p.id === selectedId ? ' pin-active' : '')
      el.type = 'button'
      el.setAttribute('aria-label', p.name)
      el.innerHTML = `<span class="pin-dot"></span><span class="pin-label">${p.name.replace(/</g, '&lt;')}</span>`
      el.addEventListener('click', () => onSelect?.(p.id))
      return new maplibregl.Marker({ element: el, anchor: 'left' }).setLngLat([p.lon, p.lat]).addTo(m)
    })
    if (properties.length && interactive && !selectedId) {
      const b = new maplibregl.LngLatBounds()
      properties.forEach(p => b.extend([p.lon, p.lat]))
      m.fitBounds(b, { padding: 90, maxZoom: 12, duration: 0 })
    }
  }, [properties, selectedId, onSelect, interactive])

  // voar até a propriedade selecionada
  useEffect(() => {
    const p = properties.find(x => x.id === selectedId)
    if (p && map.current) map.current.flyTo({ center: [p.lon, p.lat], zoom: 13.5, speed: 1.4 })
  }, [selectedId, properties])

  return <div ref={container} className="map" />
}
