/* SPA shell: sidebar + main pane + History API router.
   Routes:
     /              → home pane
     /new           → new trip form
     /availability  → park availability check
     /trips/<slug>  → rendered trip
*/

(function () {
  'use strict';

  // Auto-fill end date = start + 5 days when the end input is left empty.
  function plusDaysISO(iso, days) {
    const d = new Date(iso + 'T00:00:00');
    if (isNaN(d.getTime())) return '';
    d.setDate(d.getDate() + days);
    return d.toISOString().slice(0, 10);
  }

  function wireAutoEnd(form) {
    if (!form) return;
    const start = form.querySelector('input[name=start]');
    const end = form.querySelector('input[name=end]');
    if (!start || !end) return;
    start.addEventListener('change', function () {
      if (end.value || !start.value) return;
      const bumped = plusDaysISO(start.value, 5);
      if (bumped) end.value = bumped;
    });
  }


  const state = {
    user: '',
    trips: [],
    activeSlug: null,
  };

  const mainPane = document.getElementById('main-pane');

  // ---------------------------------------------------------------------
  // Identity (cookie-driven)
  // ---------------------------------------------------------------------
  function paintUser(name) {
    const pill = document.getElementById('user-pill');
    if (!pill) return;
    if (name) {
      pill.textContent = 'Hi, ' + name;
      pill.classList.remove('unset');
    } else {
      pill.textContent = 'Set name';
      pill.classList.add('unset');
    }
  }

  async function loadUser() {
    try {
      const r = await fetch('/api/whoami');
      const j = await r.json();
      state.user = j.user || '';
      paintUser(state.user);
      if (!state.user) promptForName();
    } catch (e) { /* offline */ }
  }

  async function setUser(name) {
    const r = await fetch('/api/whoami', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user: name }),
    });
    if (!r.ok) return false;
    const j = await r.json();
    state.user = j.user || '';
    paintUser(state.user);
    return true;
  }

  function promptForName() {
    const name = prompt("Whose checklist is this? (your first name is fine)");
    if (name && name.trim()) setUser(name.trim());
  }

  function switchUser() {
    const suggested = state.user || '';
    const name = prompt('Switch to whom? (blank = shared/anonymous)', suggested);
    if (name === null) return;
    if (!name.trim()) {
      fetch('/api/whoami', { method: 'DELETE' }).then(function () {
        state.user = ''; paintUser('');
      });
    } else {
      setUser(name.trim());
    }
  }

  // ---------------------------------------------------------------------
  // Sidebar trip list
  // ---------------------------------------------------------------------
  async function loadTrips() {
    try {
      const r = await fetch('/api/trips');
      if (!r.ok) return;
      const j = await r.json();
      state.trips = j.trips || [];
      renderSidebar();
    } catch (e) { /* offline */ }
  }

  function renderSidebar() {
    const upcoming = document.getElementById('trips-upcoming');
    const past = document.getElementById('trips-past');
    const broken = document.getElementById('trips-broken');
    const brokenLabel = document.getElementById('broken-label');
    upcoming.innerHTML = '';
    past.innerHTML = '';
    broken.innerHTML = '';

    state.trips.forEach(function (trip) {
      const li = document.createElement('li');
      const btn = document.createElement('button');
      btn.dataset.slug = trip.name;
      if (trip.bucket === 'broken') {
        btn.classList.add('broken');
        btn.innerHTML = '<span class="trip-title">' + esc(trip.name) + '</span>'
                      + '<span class="trip-meta">⚠ ' + esc(trip.error || '') + '</span>';
        btn.title = trip.error || '';
      } else {
        const meta = [trip.start_date || '', trip.days_label || ''].filter(Boolean).join(' · ');
        btn.innerHTML = '<span class="trip-title">' + esc(trip.park_name || trip.name) + '</span>'
                      + (meta ? '<span class="trip-meta">' + esc(meta) + '</span>' : '');
      }
      btn.addEventListener('click', function () { navigate('/trips/' + trip.name); });
      li.appendChild(btn);
      if (trip.bucket === 'upcoming') upcoming.appendChild(li);
      else if (trip.bucket === 'past') past.appendChild(li);
      else broken.appendChild(li);
    });
    brokenLabel.hidden = !broken.children.length;
    paintActiveSidebar();
  }

  function paintActiveSidebar() {
    document.querySelectorAll('.trip-list button').forEach(function (b) {
      b.classList.toggle('active', b.dataset.slug === state.activeSlug);
    });
    const pathname = location.pathname;
    document.querySelectorAll('.nav-btn').forEach(function (b) {
      const route = b.getAttribute('data-route');
      const match = route === '/'
        ? pathname === '/'
        : pathname.startsWith(route);
      b.classList.toggle('active', match && !pathname.startsWith('/trips/'));
    });
  }

  // ---------------------------------------------------------------------
  // Router
  // ---------------------------------------------------------------------
  function navigate(path) {
    if (location.pathname !== path) {
      history.pushState({}, '', path);
    }
    render(path);
  }

  async function render(path) {
    if (path === '/' || path === '') {
      state.activeSlug = null;
      paintActiveSidebar();
      mountTemplate('tpl-home');
      return;
    }
    if (path === '/new') {
      state.activeSlug = null;
      paintActiveSidebar();
      mountTemplate('tpl-new');
      wireNewTripForm();
      return;
    }
    if (path === '/availability') {
      state.activeSlug = null;
      paintActiveSidebar();
      mountTemplate('tpl-availability');
      wireAvailForm();
      return;
    }
    const tripMatch = path.match(/^\/trips\/([^/]+)\/?$/);
    if (tripMatch) {
      state.activeSlug = tripMatch[1];
      paintActiveSidebar();
      await renderTrip(tripMatch[1]);
      return;
    }
    mainPane.innerHTML = '<div class="main-loading">Not found.</div>';
  }

  function mountTemplate(id) {
    const tpl = document.getElementById(id);
    mainPane.innerHTML = '';
    mainPane.appendChild(tpl.content.cloneNode(true));
  }

  // ---------------------------------------------------------------------
  // Trip rendering
  // ---------------------------------------------------------------------
  async function renderTrip(slug) {
    mainPane.innerHTML = '<div class="main-loading">Loading ' + esc(slug) + '…</div>';
    let payload;
    try {
      const r = await fetch('/api/trip/' + encodeURIComponent(slug));
      if (!r.ok) {
        const j = await r.json().catch(function () { return {}; });
        const err = (j && j.detail && j.detail.error) || j.error || ('HTTP ' + r.status);
        mainPane.innerHTML = '<div class="main-loading">Error: ' + esc(err) + '</div>';
        return;
      }
      payload = await r.json();
    } catch (e) {
      mainPane.innerHTML = '<div class="main-loading">Error: ' + esc(e.message) + '</div>';
      return;
    }

    const wrap = document.createElement('div');
    wrap.className = 'trip-pane';
    wrap.innerHTML = payload.header_html
      + payload.sections.map(function (s) { return wrapSection(s); }).join('');
    mainPane.innerHTML = '';
    mainPane.appendChild(wrap);

    if (window.TripPane) {
      window.TripPane.init(wrap, slug, state.user, function () {
        renderTrip(slug);
      });
    }
  }

  function wrapSection(s) {
    const actions = s.editable
      ? '<div class="section-actions">'
        + '<button class="section-btn" data-edit="' + esc(s.id) + '">Edit</button>'
        + '<span class="section-status" data-status="' + esc(s.id) + '"></span>'
        + '</div>'
      : '';
    return '<section id="' + esc(s.id) + '">'
      + '<div class="section-header">'
      + '<h2>' + esc(s.title) + '</h2>'
      + actions
      + '</div>'
      + '<div class="section-body" data-section-body="' + esc(s.id) + '">'
      + s.html
      + '</div></section>';
  }

  // ---------------------------------------------------------------------
  // New trip form
  // ---------------------------------------------------------------------
  function wireNewTripForm() {
    const form = document.getElementById('new-trip-form');
    if (!form) return;
    wireAutoEnd(form);
    const status = form.querySelector('[data-status]');
    form.addEventListener('submit', async function (ev) {
      ev.preventDefault();
      status.className = 'status';
      status.textContent = 'Creating…';
      const body = {
        park: form.park.value,
        start: form.start.value,
        end: form.end.value,
        participants: form.participants.value.split(',').map(function (s) { return s.trim(); }).filter(Boolean),
      };
      try {
        const r = await fetch('/api/new-trip', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        });
        const j = await r.json();
        if (r.ok && j.ok) {
          status.textContent = 'Created ' + j.trip_dir;
          await loadTrips();
          navigate('/trips/' + j.trip_dir);
        } else {
          const err = (j && j.detail && j.detail.error) || j.error || 'unknown';
          status.className = 'status error';
          status.textContent = 'Error: ' + err;
        }
      } catch (e) {
        status.className = 'status error';
        status.textContent = 'Error: ' + e.message;
      }
    });
  }

  // ---------------------------------------------------------------------
  // Availability form
  // ---------------------------------------------------------------------
  function wireAvailForm() {
    const form = document.getElementById('avail-form');
    if (!form) return;
    wireAutoEnd(form);
    const out = form.parentElement.querySelector('[data-results]');
    const btn = form.querySelector('button[type=submit]');
    form.addEventListener('submit', async function (ev) {
      ev.preventDefault();
      btn.disabled = true;
      const origLabel = btn.textContent;
      btn.textContent = 'Checking…';
      out.innerHTML = '<p>Checking — this can take 5–15 seconds…</p>';
      const params = new URLSearchParams({
        park: form.park.value, start: form.start.value, end: form.end.value,
      });
      try {
        const r = await fetch('/api/availability?' + params.toString());
        const j = await r.json();
        if (r.ok && j.ok) {
          let html = '<h3>' + esc(j.park_name) + ': ' + j.total_available + ' site(s) available</h3>';
          const keys = Object.keys(j.campgrounds || {});
          if (keys.length) {
            html += '<table><thead><tr><th>Campground</th><th>Available / Total</th></tr></thead><tbody>';
            keys.forEach(function (name) {
              const info = j.campgrounds[name];
              html += '<tr><td>' + esc(name) + '</td><td>' + info.available + ' / ' + info.total + '</td></tr>';
            });
            html += '</tbody></table>';
          }
          out.innerHTML = html;
        } else {
          const err = (j && j.detail && j.detail.error) || j.error || 'unknown';
          out.innerHTML = '<p class="status error">Error: ' + esc(err) + '</p>';
        }
      } catch (e) {
        out.innerHTML = '<p class="status error">Error: ' + esc(e.message) + '</p>';
      } finally {
        btn.disabled = false;
        btn.textContent = origLabel;
      }
    });
  }

  // ---------------------------------------------------------------------
  // Plumbing
  // ---------------------------------------------------------------------
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  document.addEventListener('click', function (ev) {
    const btn = ev.target.closest('.nav-btn[data-route]');
    if (!btn) return;
    ev.preventDefault();
    navigate(btn.getAttribute('data-route'));
  });

  window.addEventListener('popstate', function () { render(location.pathname); });

  window.App = { switchUser: switchUser };

  // Boot
  Promise.all([loadUser(), loadTrips()]).then(function () {
    render(location.pathname);
  });
})();
