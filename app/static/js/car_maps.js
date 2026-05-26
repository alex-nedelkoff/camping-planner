/* Car-camping trip page maps: an OSM driving route (Ajax → park) and
   zoomable park-map image viewers. Both reuse Leaflet. No-ops if Leaflet
   or the target elements are absent, so the page never breaks. */
(function () {
  function num(v) { var n = parseFloat(v); return isNaN(n) ? null : n; }

  function initRouteMap() {
    var el = document.getElementById('route-map');
    if (!el || typeof L === 'undefined') return;
    var plat = num(el.dataset.parkLat), plon = num(el.dataset.parkLon);
    if (plat === null || plon === null) return;
    var hlat = num(el.dataset.homeLat), hlon = num(el.dataset.homeLon);
    var park = L.latLng(plat, plon);

    var map = L.map(el);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19, crossOrigin: '', attribution: '© OpenStreetMap contributors'
    }).addTo(map);

    var routed = false;
    if (L.Routing && hlat !== null && hlon !== null) {
      try {
        L.Routing.control({
          waypoints: [L.latLng(hlat, hlon), park],
          router: L.Routing.osrmv1({ serviceUrl: 'https://router.project-osrm.org/route/v1' }),
          addWaypoints: false, draggableWaypoints: false, fitSelectedRoutes: true, show: false,
          lineOptions: { styles: [{ color: '#a8451f', weight: 5, opacity: 0.85 }] },
          createMarker: function (i, wp) { return L.marker(wp.latLng); }
        }).addTo(map);
        routed = true;
      } catch (e) { routed = false; }
    }
    if (!routed) {
      L.marker(park).addTo(map);
      if (hlat !== null && hlon !== null) {
        var home = L.latLng(hlat, hlon);
        L.marker(home).addTo(map);
        L.polyline([home, park], { color: '#a8451f', weight: 3, dashArray: '6,6' }).addTo(map);
        map.fitBounds(L.latLngBounds([home, park]).pad(0.2));
      } else {
        map.setView(park, 12);
      }
    }
  }

  function initZoomableMaps() {
    if (typeof L === 'undefined') return;
    document.querySelectorAll('.zoom-map').forEach(function (el) {
      var src = el.dataset.img;
      if (!src) return;
      var probe = new Image();
      probe.onload = function () {
        var h = probe.naturalHeight, w = probe.naturalWidth;
        var map = L.map(el, { crs: L.CRS.Simple, attributionControl: false });
        var bounds = [[0, 0], [h, w]];
        L.imageOverlay(src, bounds).addTo(map);
        map.fitBounds(bounds);
        map.setMinZoom(map.getZoom());            // can't zoom out past the whole image
        map.setMaxBounds(L.latLngBounds(bounds).pad(0.3));
      };
      probe.src = src;
    });
  }

  function init() { initRouteMap(); initZoomableMaps(); }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else { init(); }
})();
