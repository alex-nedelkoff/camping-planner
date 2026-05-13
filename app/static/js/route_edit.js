// Waypoint editor — interactive Leaflet map.
// Click to add, drag to refine, right-click marker (or ✕ in the list) to delete.
// The list is the source of truth; markers are rebuilt from it whenever it changes.

const map = L.map('map', { zoomControl: true }).setView(CENTRE, ZOOM);
const baseOSM = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  maxZoom: 19,
  attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
}).addTo(map);
const baseEsri = L.tileLayer(
  'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
  { maxZoom: 19, attribution: 'Tiles © Esri' },
);
const baseTopo = L.tileLayer(
  'https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png',
  {
    maxZoom: 17,
    attribution:
      'Map data: © OpenStreetMap contributors, SRTM | Map style: © <a href="https://opentopomap.org">OpenTopoMap</a>',
  },
);

// Overlay layers — populated async from /api/lakes/{park}.
const overlayLakesOSM = L.layerGroup();
const overlayLakesJeffs = L.layerGroup();
const overlayLakesCanvec = L.layerGroup();
const overlayPortagesOSM = L.layerGroup();

const layersControl = L.control.layers(
  {
    'OpenStreetMap': baseOSM,
    'Esri satellite': baseEsri,
    'OpenTopoMap': baseTopo,
  },
  {
    'OSM lakes (named)': overlayLakesOSM,
    'OSM portages': overlayPortagesOSM,
    'CanVec lakes (NRCan)': overlayLakesCanvec,
    "Jeff's lakes (detailed)": overlayLakesJeffs,
  },
  { collapsed: false, position: 'topright' },
).addTo(map);

function styleLake(source) {
  if (source === 'jeffs') {
    return { color: '#a03030', weight: 1, fillColor: '#a03030', fillOpacity: 0.10, interactive: false };
  }
  if (source === 'canvec') {
    return { color: '#2e7d32', weight: 1, fillColor: '#2e7d32', fillOpacity: 0.10, interactive: false };
  }
  return { color: '#1565c0', weight: 1, fillColor: '#1565c0', fillOpacity: 0.12, interactive: false };
}

function stylePortage() {
  return { color: '#d27b00', weight: 3, opacity: 0.9, dashArray: '5,5' };
}

async function loadOverlays() {
  try {
    const r = await fetch(`/api/lakes/${encodeURIComponent(PARK)}`, { credentials: 'same-origin' });
    if (!r.ok) {
      console.warn(`No overlays for park ${PARK} (${r.status})`);
      return;
    }
    const data = await r.json();
    if (data.osm) {
      const fc = data.osm;
      L.geoJSON(fc, {
        filter: (f) => f.properties.kind === 'lake',
        style: () => styleLake('osm'),
      }).addTo(overlayLakesOSM);
      L.geoJSON(fc, {
        filter: (f) => f.properties.kind === 'portage',
        style: stylePortage,
        onEachFeature: (f, layer) => {
          const lk = f.properties.length_km;
          const lbl = f.properties.name + (lk ? ` (${lk.toFixed(2)} km)` : '');
          layer.bindTooltip(lbl, { sticky: true });
        },
      }).addTo(overlayPortagesOSM);
      overlayLakesOSM.addTo(map);     // on by default
      overlayPortagesOSM.addTo(map);  // on by default
    }
    if (data.canvec) {
      L.geoJSON(data.canvec, {
        style: () => styleLake('canvec'),
      }).addTo(overlayLakesCanvec);
      // off by default — CanVec is dense; toggle on for richer hydrography
    }
    if (data.jeffs) {
      L.geoJSON(data.jeffs, {
        style: () => styleLake('jeffs'),
      }).addTo(overlayLakesJeffs);
      // off by default — Jeff's is denser and noisier; toggle in if you want it
    }
  } catch (err) {
    console.warn('Overlay load failed:', err);
  }
}

loadOverlays();

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
  totalKm: document.getElementById('total-km'),
  paddleTime: document.getElementById('paddle-time'),
  speedLabel: document.getElementById('speed-label'),
  save: document.getElementById('btn-save'),
  clear: document.getElementById('btn-clear'),
  rebuild: document.getElementById('btn-rebuild'),
  status: document.getElementById('status'),
};

els.speedLabel.textContent = PADDLE_KMH.toFixed(0);

// ── Geometry ───────────────────────────────────────────────────────────────

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

// ── Rendering ──────────────────────────────────────────────────────────────

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
    const m = L.marker([w.lat, w.lon], {
      icon: makeIcon(idx),
      draggable: true,
      autoPan: true,
    });
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
  if (state.polyline) {
    map.removeLayer(state.polyline);
    state.polyline = null;
  }
  if (state.waypoints.length >= 2) {
    state.polyline = L.polyline(
      state.waypoints.map((w) => [w.lat, w.lon]),
      { color: '#3a6f55', weight: 4, opacity: 0.85 },
    ).addTo(map);
  }
}

function renderList() {
  els.list.innerHTML = '';
  if (state.waypoints.length === 0) {
    els.empty.style.display = '';
    return;
  }
  els.empty.style.display = 'none';
  state.waypoints.forEach((w, idx) => {
    const li = document.createElement('li');
    li.dataset.idx = String(idx);
    li.innerHTML = `
      <div class="idx">${idx + 1}.</div>
      <input class="name" type="text" placeholder="(unnamed)" value="${escapeHtml(w.name)}">
      <button class="del" title="Remove">✕</button>
    `;
    const input = li.querySelector('.name');
    input.addEventListener('input', (ev) => {
      state.waypoints[idx].name = ev.target.value;
      markDirty();
    });
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
  for (const li of els.list.querySelectorAll('li')) li.classList.remove('active');
  const li = els.list.querySelector(`li[data-idx="${idx}"]`);
  if (li) li.classList.add('active');
  if (panMap) {
    const w = state.waypoints[idx];
    if (w) map.panTo([w.lat, w.lon]);
  }
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

// ── Mutations ──────────────────────────────────────────────────────────────

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

// ── Save / Rebuild ────────────────────────────────────────────────────────

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
    if (!r.ok) {
      const text = await r.text();
      throw new Error(`${r.status}: ${text}`);
    }
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
    setStatus('Trip rebuilt — refresh the trip page to see the new route.', 'ok');
  } catch (err) {
    setStatus(`Rebuild failed: ${err.message}`, 'error');
  }
}

// ── Wire up ────────────────────────────────────────────────────────────────

map.on('click', (ev) => {
  addWaypoint(ev.latlng.lat, ev.latlng.lng);
});

els.save.addEventListener('click', save);
els.clear.addEventListener('click', clearAll);
els.rebuild.addEventListener('click', rebuild);

window.addEventListener('beforeunload', (ev) => {
  if (state.dirty) {
    ev.preventDefault();
    ev.returnValue = '';
  }
});

// Initial render. If we loaded saved waypoints, fit the map to them.
renderAll();
if (state.waypoints.length >= 2) {
  const bounds = L.latLngBounds(state.waypoints.map((w) => [w.lat, w.lon]));
  map.fitBounds(bounds, { padding: [40, 40] });
}
els.save.disabled = !state.dirty;
