// Waypoint editor — Leaflet map fills the viewport; the floating side panel
// drives base-map radios, overlay checkboxes, raster opacity, and the
// waypoint list. The list is the source of truth for waypoints; markers and
// the polyline are rebuilt from it whenever it changes.

// ── Map + base layers ─────────────────────────────────────────────────────

const map = L.map('map', { zoomControl: true }).setView(CENTRE, ZOOM);

const baseLayers = {
  osm: L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
  }),
  topo: L.tileLayer('https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png', {
    maxZoom: 17,
    attribution: 'Map: © OpenStreetMap, SRTM | © <a href="https://opentopomap.org">OpenTopoMap</a>',
  }),
  esri: L.tileLayer(
    'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    { maxZoom: 19, attribution: 'Tiles © Esri' },
  ),
};
let activeBase = baseLayers.osm.addTo(map);

document.querySelectorAll('input[name="base"]').forEach((radio) => {
  radio.addEventListener('change', () => {
    if (!radio.checked) return;
    const next = baseLayers[radio.value];
    if (!next || next === activeBase) return;
    map.removeLayer(activeBase);
    activeBase = next.addTo(map);
  });
});

// ── Overlays ──────────────────────────────────────────────────────────────

const rasterLayer = RASTER_URL
  ? L.imageOverlay(RASTER_URL, RASTER_BOUNDS, { opacity: 0.7 })
  : null;
if (rasterLayer) rasterLayer.addTo(map);

const overlayPortagesOSM = L.layerGroup();
const overlayPortagesGPX = L.layerGroup();
const overlayCanvec = L.layerGroup();
const overlayCampsites = L.layerGroup();

function styleLake() {
  return { color: '#006064', weight: 1, fillColor: '#006064', fillOpacity: 0.10, interactive: false };
}
function stylePortageOSM() {
  return { color: '#d27b00', weight: 3, opacity: 0.9, dashArray: '5,5' };
}
function stylePortageGPX() {
  return { color: '#7b1fa2', weight: 3, opacity: 0.85 };
}

function campsiteIcon(name) {
  return L.divIcon({
    className: 'campsite-marker',
    html: String(name || '•'),
    iconSize: [22, 22],
    iconAnchor: [11, 11],
  });
}

async function loadOverlays() {
  try {
    const r = await fetch(`/api/lakes/${encodeURIComponent(PARK)}`, { credentials: 'same-origin' });
    if (!r.ok) return;
    const data = await r.json();
    if (data.osm) {
      L.geoJSON(data.osm, {
        filter: (f) => f.properties.kind === 'portage',
        style: stylePortageOSM,
        onEachFeature: (f, layer) => {
          const lk = f.properties.length_km;
          const lbl = f.properties.name + (lk ? ` (${lk.toFixed(2)} km)` : '');
          layer.bindTooltip(lbl, { sticky: true });
        },
      }).addTo(overlayPortagesOSM);
      // off by default — superseded by the GPX portages set
    }
    if (data.canvec) {
      L.geoJSON(data.canvec, { style: styleLake }).addTo(overlayCanvec);
      overlayCanvec.addTo(map);
    }
    if (data.portages) {
      L.geoJSON(data.portages, {
        style: stylePortageGPX,
        onEachFeature: (f, layer) => {
          const km = f.properties.length_km;
          const lbl = `Portage ${f.properties.name}` + (km ? ` · ${km.toFixed(2)} km` : '');
          layer.bindTooltip(lbl, { sticky: true });
        },
      }).addTo(overlayPortagesGPX);
      overlayPortagesGPX.addTo(map);
    }
    if (data.campsites) {
      L.geoJSON(data.campsites, {
        pointToLayer: (f, latlng) => L.marker(latlng, {
          icon: campsiteIcon(f.properties.name),
          // Don't grab clicks meant for waypoint placement — only the marker
          // itself reacts, not the surrounding square.
          interactive: true,
          keyboard: false,
        }),
        onEachFeature: (f, layer) => {
          const p = f.properties;
          const lines = [`Site ${p.name}`];
          if (p.type) lines.push(p.type);
          if (p.desc) lines.push(p.desc);
          layer.bindTooltip(lines.join(' · '), { direction: 'top', sticky: true });
        },
      }).addTo(overlayCampsites);
      overlayCampsites.addTo(map);
    }
  } catch (err) {
    console.warn('Overlay load failed:', err);
  }
}

// ── Custom panel controls (overlay checkboxes + opacity slider) ───────────

function wireOverlayToggle(checkboxId, layer) {
  const box = document.getElementById(checkboxId);
  if (!layer) { box.disabled = true; box.checked = false; return; }
  box.addEventListener('change', () => {
    if (box.checked) layer.addTo(map);
    else map.removeLayer(layer);
  });
}
wireOverlayToggle('ov-raster', rasterLayer);
wireOverlayToggle('ov-canvec', overlayCanvec);
wireOverlayToggle('ov-portages-gpx', overlayPortagesGPX);
wireOverlayToggle('ov-campsites', overlayCampsites);
wireOverlayToggle('ov-portages-osm', overlayPortagesOSM);

(function wireRasterSlider() {
  const slider = document.getElementById('raster-opacity');
  const label = document.getElementById('raster-opacity-val');
  const box = document.getElementById('ov-raster');
  if (!rasterLayer) { slider.disabled = true; label.textContent = 'n/a'; return; }
  slider.addEventListener('input', (ev) => {
    const v = parseFloat(ev.target.value);
    label.textContent = `${Math.round(v * 100)}%`;
    rasterLayer.setOpacity(v);
    if (v > 0 && !box.checked) {
      box.checked = true;
      rasterLayer.addTo(map);
    }
  });
})();

// ── Waypoint state + rendering ────────────────────────────────────────────

const state = {
  waypoints: INITIAL.map((w) => ({ lat: w.lat, lon: w.lon, name: w.name || '' })),
  markers: [],
  polyline: null,
  dirty: false,
  saving: false,
};

const els = {
  list: document.getElementById('wp-list'),
  empty: document.getElementById('wp-empty'),
  count: document.getElementById('wp-count'),
  totalKm: document.getElementById('total-km'),
  paddleTime: document.getElementById('paddle-time'),
  save: document.getElementById('btn-save'),
  clear: document.getElementById('btn-clear'),
  rebuild: document.getElementById('btn-rebuild'),
  status: document.getElementById('status'),
};

function haversineKm(a, b) {
  const R = 6371.0088;
  const toRad = (d) => (d * Math.PI) / 180;
  const dLat = toRad(b.lat - a.lat);
  const dLon = toRad(b.lon - a.lon);
  const s1 = Math.sin(dLat / 2);
  const s2 = Math.sin(dLon / 2);
  const h = s1 * s1 + Math.cos(toRad(a.lat)) * Math.cos(toRad(b.lat)) * s2 * s2;
  return 2 * R * Math.asin(Math.sqrt(h));
}

function totalKm() {
  let d = 0;
  for (let i = 1; i < state.waypoints.length; i += 1) {
    d += haversineKm(state.waypoints[i - 1], state.waypoints[i]);
  }
  return d;
}

function formatTime(km) {
  if (km <= 0) return '—';
  const hours = km / PADDLE_KMH;
  const h = Math.floor(hours);
  const m = Math.round((hours - h) * 60);
  if (h === 0) return `${m}m`;
  if (m === 0) return `${h}h`;
  return `${h}h ${m}m`;
}

function makeIcon(idx) {
  return L.divIcon({
    className: 'wp-marker',
    html: String(idx + 1),
    iconSize: [26, 26],
    iconAnchor: [13, 13],
  });
}

function rebuildMarkers() {
  state.markers.forEach((m) => map.removeLayer(m));
  state.markers = state.waypoints.map((w, idx) => {
    const m = L.marker([w.lat, w.lon], { icon: makeIcon(idx), draggable: true, autoPan: true });
    m.on('dragend', (ev) => {
      const ll = ev.target.getLatLng();
      state.waypoints[idx].lat = ll.lat;
      state.waypoints[idx].lon = ll.lng;
      markDirty();
      renderList();
      renderPolyline();
      renderStats();
    });
    m.on('contextmenu', () => removeAt(idx));
    m.on('click', () => focusRow(idx));
    return m.addTo(map);
  });
}

function renderPolyline() {
  if (state.polyline) { map.removeLayer(state.polyline); state.polyline = null; }
  if (state.waypoints.length >= 2) {
    state.polyline = L.polyline(
      state.waypoints.map((w) => [w.lat, w.lon]),
      { color: '#6b1fb1', weight: 4, opacity: 0.85 },
    ).addTo(map);
  }
}

function renderList() {
  els.list.innerHTML = '';
  els.count.textContent = `${state.waypoints.length} pt${state.waypoints.length === 1 ? '' : 's'}`;
  if (state.waypoints.length === 0) { els.empty.style.display = ''; return; }
  els.empty.style.display = 'none';
  state.waypoints.forEach((w, idx) => {
    const li = document.createElement('li');
    li.dataset.idx = String(idx);
    li.innerHTML = `
      <div class="idx">${idx + 1}.</div>
      <input class="name" type="text" placeholder="(unnamed)">
      <button class="del" title="Remove">✕</button>
    `;
    const input = li.querySelector('.name');
    input.value = w.name;
    input.addEventListener('input', (ev) => { state.waypoints[idx].name = ev.target.value; markDirty(); });
    li.querySelector('.del').addEventListener('click', () => removeAt(idx));
    li.addEventListener('click', (ev) => {
      if (ev.target === input || ev.target.classList.contains('del')) return;
      focusRow(idx, { panMap: true });
    });
    els.list.appendChild(li);
  });
}

function renderStats() {
  const km = totalKm();
  els.totalKm.textContent = km.toFixed(2);
  els.paddleTime.textContent = formatTime(km);
}

function renderAll() {
  rebuildMarkers();
  renderPolyline();
  renderList();
  renderStats();
}

function focusRow(idx, { panMap = false } = {}) {
  els.list.querySelectorAll('li').forEach((li) => li.classList.remove('active'));
  const li = els.list.querySelector(`li[data-idx="${idx}"]`);
  if (li) li.classList.add('active');
  if (panMap) {
    const w = state.waypoints[idx];
    if (w) map.panTo([w.lat, w.lon]);
  }
}

function addWaypoint(lat, lon) {
  state.waypoints.push({ lat, lon, name: '' });
  markDirty();
  renderAll();
}

function removeAt(idx) {
  state.waypoints.splice(idx, 1);
  markDirty();
  renderAll();
}

function clearAll() {
  if (state.waypoints.length === 0) return;
  if (!confirm('Remove all waypoints?')) return;
  state.waypoints = [];
  markDirty();
  renderAll();
}

function markDirty() {
  state.dirty = true;
  els.save.disabled = state.saving;
  setStatus('');
}

function setStatus(msg, kind) {
  els.status.textContent = msg;
  els.status.className = 'status' + (kind ? ' ' + kind : '');
}

async function save() {
  if (state.saving) return;
  state.saving = true;
  els.save.disabled = true;
  setStatus('Saving…');
  try {
    const r = await fetch(`/api/trips/${encodeURIComponent(SLUG)}/route`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({ waypoints: state.waypoints }),
    });
    if (!r.ok) throw new Error(`${r.status}: ${await r.text()}`);
    const data = await r.json();
    state.dirty = false;
    setStatus(`Saved ${data.saved} waypoint(s) · ${data.total_km} km`, 'ok');
  } catch (err) {
    setStatus(`Save failed: ${err.message}`, 'error');
  } finally {
    state.saving = false;
    els.save.disabled = !state.dirty;
  }
}

async function rebuild() {
  setStatus('Rebuilding trip page…');
  try {
    const r = await fetch(`/api/rebuild?trip=${encodeURIComponent(SLUG)}`, {
      method: 'POST', credentials: 'same-origin',
    });
    if (!r.ok) throw new Error(`${r.status}: ${await r.text()}`);
    setStatus('Trip rebuilt — refresh the trip page to see it.', 'ok');
  } catch (err) {
    setStatus(`Rebuild failed: ${err.message}`, 'error');
  }
}

// ── Wire up ───────────────────────────────────────────────────────────────

map.on('click', (ev) => addWaypoint(ev.latlng.lat, ev.latlng.lng));
els.save.addEventListener('click', save);
els.clear.addEventListener('click', clearAll);
els.rebuild.addEventListener('click', rebuild);

window.addEventListener('beforeunload', (ev) => {
  if (state.dirty) { ev.preventDefault(); ev.returnValue = ''; }
});

loadOverlays();
renderAll();
if (state.waypoints.length >= 2) {
  const bounds = L.latLngBounds(state.waypoints.map((w) => [w.lat, w.lon]));
  map.fitBounds(bounds, { padding: [40, 40] });
}
els.save.disabled = !state.dirty;
