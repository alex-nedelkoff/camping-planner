/* Waypoint editor — mounted into the SPA main-pane by index.js when the URL
   matches /trips/<slug>/route-edit.
   Backend contract: GET /api/trips/<slug>/route-meta (centre, zoom, raster,
   seed waypoints), GET /api/lakes/<park> (overlays), POST /api/trips/<slug>/route.
*/

(function (global) {
  'use strict';

  const PADDLE_KMH = 4.0;

  async function mount(root, slug) {
    root.innerHTML = '<div class="main-loading">Loading route editor…</div>';
    let meta;
    try {
      const r = await fetch('/api/trips/' + encodeURIComponent(slug) + '/route-meta');
      if (!r.ok) {
        root.innerHTML = '<div class="main-loading">Trip not found.</div>';
        return;
      }
      meta = await r.json();
    } catch (e) {
      root.innerHTML = '<div class="main-loading">Error: ' + e.message + '</div>';
      return;
    }

    const tpl = document.getElementById('tpl-route-edit');
    root.innerHTML = '';
    root.appendChild(tpl.content.cloneNode(true));

    const ui = {
      mapEl: root.querySelector('#route-map'),
      title: root.querySelector('[data-park-title]'),
      back: root.querySelector('[data-back-link]'),
      wpCount: root.querySelector('[data-wp-count]'),
      totalKm: root.querySelector('[data-total-km]'),
      paddleTime: root.querySelector('[data-paddle-time]'),
      list: root.querySelector('[data-wp-list]'),
      empty: root.querySelector('[data-wp-empty]'),
      save: root.querySelector('[data-action="save"]'),
      clear: root.querySelector('[data-action="clear"]'),
      status: root.querySelector('[data-status]'),
      rasterOpacity: root.querySelector('[data-raster-opacity]'),
      rasterOpacityVal: root.querySelector('[data-raster-opacity-val]'),
      baseRadios: root.querySelectorAll('input[name=re-base]'),
      overlayBoxes: root.querySelectorAll('input[data-ov]'),
    };

    ui.title.textContent = (meta.park || 'Trip').replace(/^./, (c) => c.toUpperCase());
    ui.back.setAttribute('href', '/trips/' + encodeURIComponent(slug));
    ui.back.addEventListener('click', (ev) => {
      ev.preventDefault();
      if (window.App && window.App.navigate) window.App.navigate('/trips/' + slug);
      else window.location.href = '/trips/' + slug;
    });

    // ── Map + base layers ────────────────────────────────────────────────
    const map = L.map(ui.mapEl, { zoomControl: true }).setView(meta.centre, meta.zoom || 12);
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
    ui.baseRadios.forEach((radio) => {
      radio.addEventListener('change', () => {
        if (!radio.checked) return;
        const next = baseLayers[radio.value];
        if (!next || next === activeBase) return;
        map.removeLayer(activeBase);
        activeBase = next.addTo(map);
      });
    });

    // ── Overlays ────────────────────────────────────────────────────────
    const rasterLayer = meta.raster_url
      ? L.imageOverlay(meta.raster_url, meta.raster_bounds, { opacity: 0.7 })
      : null;
    if (rasterLayer) rasterLayer.addTo(map);

    const groups = {
      'canvec': L.layerGroup(),
      'portages': L.layerGroup(),
      'campsites': L.layerGroup(),
      'osm-portages': L.layerGroup(),
    };
    const lakeStyle = () => ({ color: '#006064', weight: 1, fillColor: '#006064', fillOpacity: 0.10, interactive: false });
    const portageGpxStyle = () => ({ color: '#7b1fa2', weight: 3, opacity: 0.85 });
    const portageOsmStyle = () => ({ color: '#d27b00', weight: 3, opacity: 0.9, dashArray: '5,5' });
    function campsiteIcon(name) {
      return L.divIcon({
        className: 'campsite-marker',
        html: String(name || '•'),
        iconSize: [22, 22], iconAnchor: [11, 11],
      });
    }

    try {
      const r = await fetch('/api/lakes/' + encodeURIComponent(meta.park));
      if (r.ok) {
        const data = await r.json();
        if (data.osm) {
          L.geoJSON(data.osm, {
            filter: (f) => f.properties.kind === 'portage',
            style: portageOsmStyle,
            onEachFeature: (f, layer) => {
              const lk = f.properties.length_km;
              const lbl = f.properties.name + (lk ? ' (' + lk.toFixed(2) + ' km)' : '');
              layer.bindTooltip(lbl, { sticky: true });
            },
          }).addTo(groups['osm-portages']);
        }
        if (data.canvec) {
          L.geoJSON(data.canvec, { style: lakeStyle }).addTo(groups['canvec']);
          groups['canvec'].addTo(map);
        }
        if (data.portages) {
          L.geoJSON(data.portages, {
            style: portageGpxStyle,
            onEachFeature: (f, layer) => {
              const km = f.properties.length_km;
              const lbl = 'Portage ' + f.properties.name + (km ? ' · ' + km.toFixed(2) + ' km' : '');
              layer.bindTooltip(lbl, { sticky: true });
            },
          }).addTo(groups['portages']);
          groups['portages'].addTo(map);
        }
        if (data.campsites) {
          L.geoJSON(data.campsites, {
            pointToLayer: (f, latlng) => L.marker(latlng, {
              icon: campsiteIcon(f.properties.name), keyboard: false,
            }),
            onEachFeature: (f, layer) => {
              const p = f.properties;
              const parts = ['Site ' + p.name];
              if (p.type) parts.push(p.type);
              if (p.desc) parts.push(p.desc);
              layer.bindTooltip(parts.join(' · '), { direction: 'top', sticky: true });
            },
          }).addTo(groups['campsites']);
          groups['campsites'].addTo(map);
        }
      }
    } catch (e) {
      console.warn('Overlay load failed:', e);
    }

    ui.overlayBoxes.forEach((box) => {
      const key = box.dataset.ov;
      const layer = key === 'raster' ? rasterLayer : groups[key];
      if (!layer) {
        box.disabled = true; box.checked = false; return;
      }
      box.addEventListener('change', () => {
        if (box.checked) layer.addTo(map);
        else map.removeLayer(layer);
      });
    });

    if (rasterLayer) {
      ui.rasterOpacity.addEventListener('input', (ev) => {
        const v = parseFloat(ev.target.value);
        ui.rasterOpacityVal.textContent = Math.round(v * 100) + '%';
        rasterLayer.setOpacity(v);
        const box = root.querySelector('input[data-ov="raster"]');
        if (v > 0 && !box.checked) { box.checked = true; rasterLayer.addTo(map); }
      });
    } else {
      ui.rasterOpacity.disabled = true;
      ui.rasterOpacityVal.textContent = 'n/a';
    }

    // ── Waypoint state + rendering ──────────────────────────────────────
    const state = {
      waypoints: (meta.waypoints || []).map((w) => ({ lat: w.lat, lon: w.lon, name: w.name || '' })),
      markers: [], polyline: null, dirty: false, saving: false,
    };

    function haversineKm(a, b) {
      const R = 6371.0088, toRad = (d) => d * Math.PI / 180;
      const dLat = toRad(b.lat - a.lat), dLon = toRad(b.lon - a.lon);
      const h = Math.sin(dLat / 2) ** 2 + Math.cos(toRad(a.lat)) * Math.cos(toRad(b.lat)) * Math.sin(dLon / 2) ** 2;
      return 2 * R * Math.asin(Math.sqrt(h));
    }
    function totalKm() {
      let d = 0;
      for (let i = 1; i < state.waypoints.length; i += 1) d += haversineKm(state.waypoints[i-1], state.waypoints[i]);
      return d;
    }
    function formatTime(km) {
      if (km <= 0) return '—';
      const hours = km / PADDLE_KMH, h = Math.floor(hours), m = Math.round((hours - h) * 60);
      if (h === 0) return m + 'm'; if (m === 0) return h + 'h'; return h + 'h ' + m + 'm';
    }
    function makeIcon(idx) {
      return L.divIcon({
        className: 'wp-marker', html: String(idx + 1),
        iconSize: [26, 26], iconAnchor: [13, 13],
      });
    }
    function rebuildMarkers() {
      state.markers.forEach((m) => map.removeLayer(m));
      state.markers = state.waypoints.map((w, idx) => {
        const m = L.marker([w.lat, w.lon], { icon: makeIcon(idx), draggable: true, autoPan: true });
        m.on('dragend', (ev) => {
          const ll = ev.target.getLatLng();
          state.waypoints[idx].lat = ll.lat; state.waypoints[idx].lon = ll.lng;
          markDirty(); renderList(); renderPolyline(); renderStats();
        });
        m.on('contextmenu', () => removeAt(idx));
        return m.addTo(map);
      });
    }
    function renderPolyline() {
      if (state.polyline) { map.removeLayer(state.polyline); state.polyline = null; }
      if (state.waypoints.length >= 2) {
        state.polyline = L.polyline(state.waypoints.map((w) => [w.lat, w.lon]),
          { color: '#6b1fb1', weight: 4, opacity: 0.85 }).addTo(map);
      }
    }
    function renderList() {
      ui.list.innerHTML = '';
      ui.wpCount.textContent = state.waypoints.length + ' pt' + (state.waypoints.length === 1 ? '' : 's');
      if (state.waypoints.length === 0) { ui.empty.style.display = ''; return; }
      ui.empty.style.display = 'none';
      state.waypoints.forEach((w, idx) => {
        const li = document.createElement('li');
        li.dataset.idx = String(idx);
        li.innerHTML = '<div class="idx">' + (idx + 1) + '.</div>'
          + '<input class="name" type="text" placeholder="(unnamed)">'
          + '<button class="del" title="Remove">✕</button>';
        const input = li.querySelector('.name');
        input.value = w.name;
        input.addEventListener('input', (ev) => { state.waypoints[idx].name = ev.target.value; markDirty(); });
        li.querySelector('.del').addEventListener('click', () => removeAt(idx));
        ui.list.appendChild(li);
      });
    }
    function renderStats() {
      const km = totalKm();
      ui.totalKm.textContent = km.toFixed(2);
      ui.paddleTime.textContent = formatTime(km);
    }
    function renderAll() { rebuildMarkers(); renderPolyline(); renderList(); renderStats(); }

    function addWaypoint(lat, lon) { state.waypoints.push({ lat, lon, name: '' }); markDirty(); renderAll(); }
    function removeAt(idx) { state.waypoints.splice(idx, 1); markDirty(); renderAll(); }
    function markDirty() { state.dirty = true; ui.save.disabled = state.saving; setStatus(''); }
    function setStatus(msg, kind) {
      ui.status.textContent = msg;
      ui.status.className = 'status' + (kind ? ' ' + kind : '');
    }

    async function save() {
      if (state.saving) return;
      state.saving = true; ui.save.disabled = true; setStatus('Saving…');
      try {
        const r = await fetch('/api/trips/' + encodeURIComponent(slug) + '/route', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          credentials: 'same-origin',
          body: JSON.stringify({ waypoints: state.waypoints }),
        });
        if (!r.ok) throw new Error(r.status + ': ' + await r.text());
        const data = await r.json();
        state.dirty = false;
        setStatus('Saved ' + data.saved + ' waypoint(s) · ' + data.total_km + ' km', 'ok');
      } catch (err) { setStatus('Save failed: ' + err.message, 'error'); }
      finally { state.saving = false; ui.save.disabled = !state.dirty; }
    }
    function clearAll() {
      if (state.waypoints.length === 0) return;
      if (!confirm('Remove all waypoints?')) return;
      state.waypoints = []; markDirty(); renderAll();
    }

    map.on('click', (ev) => addWaypoint(ev.latlng.lat, ev.latlng.lng));
    ui.save.addEventListener('click', save);
    ui.clear.addEventListener('click', clearAll);

    renderAll();
    if (state.waypoints.length >= 2) {
      map.fitBounds(L.latLngBounds(state.waypoints.map((w) => [w.lat, w.lon])), { padding: [40, 40] });
    }
    ui.save.disabled = !state.dirty;

    // Leaflet needs an explicit size hint after the container becomes visible.
    setTimeout(() => map.invalidateSize(), 50);
  }

  global.RouteEditor = { mount: mount };
})(window);
