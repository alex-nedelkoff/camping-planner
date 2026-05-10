"""
Generate a self-contained trip HTML page from a directory of markdown files.

Usage: python3 build_trip.py trips/<trip-name>/
"""

import argparse
import datetime
import json
import re
import sys
from html import escape
from pathlib import Path

import markdown as _md
import yaml

import weather as _weather
import route_map as _route_map
import osm_data as _osm_data
import route_engine as _route_engine

# Weather data provider — defaults to direct Open-Meteo lookup. The FastAPI
# layer swaps this for a SQLite-cached version (see app/services/trips.py) so
# repeated rebuilds skip the network. CLI invocations stay zero-dep.
weather_provider = _weather.get_weather

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SECTION_FILES = ["itinerary", "gear", "food", "packing", "costs"]
FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n?(.*)", re.DOTALL)
TASK_LINE_RE = re.compile(
    r"^(?P<prefix>\s*[-*+]\s+)\[(?P<mark>[ xX])\]\s+(?P<label>.+)$",
    re.MULTILINE,
)

_PAGE_CSS = """
* { box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
       max-width: 900px; margin: 0 auto; padding: 1.5rem; color: #222;
       line-height: 1.55; background: #f0eee6; }
h1, h2, h3 { color: #1f3a3a; }
h1 { border-bottom: 3px solid #2d5016; padding-bottom: 0.3rem; }
section { background: white; padding: 0; margin: 1.5rem 0;
          border-radius: 10px; box-shadow: 0 2px 6px rgba(0,0,0,0.08);
          overflow: hidden; border: 1px solid #d8d4c5; }
.section-header { background: linear-gradient(90deg, #2d5016 0%, #3a6420 100%);
                  color: white; padding: 0.85rem 1.5rem; display: flex;
                  justify-content: space-between; align-items: center; gap: 1rem;
                  border-bottom: 4px solid #1f3a3a; }
.section-header h2 { color: white; margin: 0; font-size: 1.4rem;
                     border-bottom: none; font-weight: 700;
                     letter-spacing: 0.02em; }
.section-body { padding: 1.25rem 1.5rem; }
.section-body > h2:first-child { display: none; }
table { width: 100%; border-collapse: collapse; margin: 0.5rem 0; }
th, td { text-align: left; padding: 0.4rem 0.6rem; border-bottom: 1px solid #eee; }
th { background: #f0f4ee; }
input[type=checkbox] { margin-right: 0.5rem; transform: scale(1.2); }
.trip-header { background: #2d5016; color: white; padding: 1.5rem 1.5rem 1rem;
               border-radius: 10px; margin-bottom: 1rem; position: relative; }
.trip-header h1 { color: white; border-bottom: none; margin: 0 0 0.5rem; }
.user-pill { position: absolute; top: 1rem; right: 1rem; background: rgba(0,0,0,0.25);
             color: white; padding: 0.3rem 0.7rem; border-radius: 999px;
             font-size: 0.85rem; cursor: pointer; border: none; font-family: inherit; }
.user-pill:hover { background: rgba(0,0,0,0.4); }
.user-pill.unset { background: rgba(255,255,255,0.18); font-style: italic; }
.trip-meta { display: flex; gap: 1.5rem; flex-wrap: wrap; opacity: 0.95; }
.trip-header table { background: rgba(0,0,0,0.18); border-radius: 6px;
                     overflow: hidden; margin-top: 1rem; }
.trip-header th, .trip-header td { color: white;
                     border-bottom: 1px solid rgba(255,255,255,0.18);
                     padding: 0.5rem 0.75rem; }
.trip-header th { background: rgba(0,0,0,0.28); font-weight: 600; }
.trip-header tr:last-child td { border-bottom: none; }
.section-actions { display: flex; gap: 0.4rem; align-items: center; }
.section-btn { padding: 0.3rem 0.75rem; background: rgba(255,255,255,0.18);
               color: white; border: 1px solid rgba(255,255,255,0.35);
               border-radius: 5px; cursor: pointer;
               font-size: 0.85rem; font-family: inherit; }
.section-btn:hover { background: rgba(255,255,255,0.3); }
.section-btn:disabled { opacity: 0.55; cursor: not-allowed; }
.section-status { font-size: 0.85rem; color: rgba(255,255,255,0.85);
                  margin-left: 0.25rem; }
.section-status.error { color: #ffd0d0; }
.section-editor { display: flex; flex-direction: column; gap: 0.6rem; }
.section-editor textarea { width: 100%; min-height: 14rem;
                           padding: 0.75rem; border: 1px solid #ccc;
                           border-radius: 6px; font-family: 'SF Mono',
                           Menlo, Consolas, monospace; font-size: 0.9rem;
                           line-height: 1.5; resize: vertical; }
.gear-edit-toolbar { margin-top: 0.6rem; display: flex; gap: 0.5rem;
                     align-items: center; flex-wrap: wrap; }
.gear-btn { padding: 0.35rem 0.85rem; background: #2d5016; color: white;
            border: none; border-radius: 5px; cursor: pointer;
            font-size: 0.9rem; font-family: inherit; }
.gear-btn:hover { background: #3a6420; }
.gear-btn.secondary { background: #6b7a5a; }
.gear-btn:disabled { opacity: 0.5; cursor: not-allowed; }
#gear table.editing td { background: #fffbe6; }
#gear table.editing td[contenteditable=true]:focus { outline: 2px solid #2d5016;
                     outline-offset: -2px; background: #fff; }
#gear .row-del { background: transparent; border: none; color: #c00;
                 cursor: pointer; font-size: 1.1rem; padding: 0 0.3rem;
                 margin-left: 0.4rem; }
.gear-status { font-size: 0.9rem; color: #555; margin-left: 0.25rem; }
.gear-status.error { color: #c00; }
@media print { body { background: white; } section { box-shadow: none; }
               .gear-edit-toolbar, .section-actions { display: none; }
               .section-header { background: white; color: #1f3a3a;
                                 border-bottom: 2px solid #2d5016; }
               .section-header h2 { color: #1f3a3a; } }
"""

_PAGE_JS = r"""
(function() {
  var slugMatch = location.pathname.match(/\/trips\/([^/]+)\//);
  var tripSlug = slugMatch ? slugMatch[1] : null;
  var boxes = document.querySelectorAll('input[type=checkbox][data-cb-key]');

  // localStorage key is namespaced per-user so switching identity on the same
  // device doesn't bleed checks. '' = shared (matches Phase 2 behaviour).
  var currentUser = '';
  function lkey(cbKey) { return 'cb:' + currentUser + ':' + cbKey; }

  function applyLocal(cb) {
    var saved = localStorage.getItem(lkey(cb.dataset.cbKey));
    if (saved === '1') cb.checked = true;
    else if (saved === '0') cb.checked = false;
    else cb.checked = false;
  }

  function hydrateFromServer() {
    if (!tripSlug) return Promise.resolve();
    return fetch('/api/checklist?trip=' + encodeURIComponent(tripSlug))
      .then(function(r) { return r.ok ? r.json() : null; })
      .then(function(j) {
        if (!j || !j.ok || !j.state) return;
        boxes.forEach(function(cb) {
          if (Object.prototype.hasOwnProperty.call(j.state, cb.dataset.cbKey)) {
            cb.checked = !!j.state[cb.dataset.cbKey];
            localStorage.setItem(lkey(cb.dataset.cbKey), cb.checked ? '1' : '0');
          }
        });
      })
      .catch(function() { /* offline */ });
  }

  function refreshChecklist() {
    boxes.forEach(applyLocal);
    return hydrateFromServer();
  }

  boxes.forEach(function(cb) {
    cb.addEventListener('change', function() {
      localStorage.setItem(lkey(cb.dataset.cbKey), cb.checked ? '1' : '0');
      if (!tripSlug) return;
      fetch('/api/checklist?trip=' + encodeURIComponent(tripSlug), {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({key: cb.dataset.cbKey, checked: cb.checked})
      }).catch(function() {});
    });
  });

  // --- Identity (cookie-based) ---
  function paintUser(name) {
    var pill = document.getElementById('user-pill');
    if (!pill) return;
    if (name) {
      pill.textContent = 'Hi, ' + name;
      pill.classList.remove('unset');
    } else {
      pill.textContent = 'Set name';
      pill.classList.add('unset');
    }
  }

  function loadUser() {
    return fetch('/api/whoami')
      .then(function(r) { return r.json(); })
      .then(function(j) {
        currentUser = j.user || '';
        paintUser(currentUser);
        return refreshChecklist();
      })
      .catch(function() { return refreshChecklist(); });
  }

  window.switchUser = function() {
    var current = currentUser || '';
    var name = prompt('Switch to whom? (blank = shared/anonymous)', current);
    if (name === null) return;
    var trimmed = name.trim();
    var op = trimmed
      ? fetch('/api/whoami', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({user: trimmed})
        }).then(function(r) { return r.json(); })
      : fetch('/api/whoami', {method: 'DELETE'}).then(function() { return {user: ''}; });
    op.then(function(j) {
      currentUser = (j && j.user) || '';
      paintUser(currentUser);
      return refreshChecklist();
    }).catch(function() {});
  };

  loadUser();
})();

// --- In-place table row editor (gear, costs, ...) ---
(function() {
  var slugMatch = location.pathname.match(/\/trips\/([^/]+)\//);
  var tripSlug = slugMatch ? slugMatch[1] : null;

  Array.from(document.querySelectorAll('button[data-edit][data-edit-mode=table]'))
    .forEach(function(headerBtn) {
      var sectionId = headerBtn.dataset.edit;
      attachTableEditor(sectionId, headerBtn);
    });

  function attachTableEditor(sectionId, headerBtn) {
    var section = document.getElementById(sectionId);
    if (!section) return;
    var table = section.querySelector('table');
    if (!table) return;
    var tbody = table.querySelector('tbody');
    if (!tbody) return;
    var status = section.querySelector('[data-status="' + sectionId + '"]');

    var ncols = 0;
    var firstRow = tbody.querySelector('tr');
    if (firstRow) ncols = firstRow.cells.length;
    if (!ncols) {
      var theadRow = table.querySelector('thead tr');
      if (theadRow) ncols = theadRow.cells.length;
    }
    if (!ncols) return;

    // Toolbar lives below the table; section-header Edit toggles into edit mode.
    var toolbar = document.createElement('div');
    toolbar.className = 'gear-edit-toolbar';
    toolbar.innerHTML =
      '<button class="gear-btn" data-act="add" hidden>+ Add row</button>' +
      '<button class="gear-btn" data-act="save" hidden>Save</button>' +
      '<button class="gear-btn secondary" data-act="cancel" hidden>Cancel</button>';
    table.after(toolbar);

    var addBtn = toolbar.querySelector('[data-act=add]');
    var saveBtn = toolbar.querySelector('[data-act=save]');
    var cancelBtn = toolbar.querySelector('[data-act=cancel]');

    var snapshot = null;

    function setStatus(text, isError) {
      if (!status) return;
      status.textContent = text || '';
      status.className = 'section-status' + (isError ? ' error' : '');
    }

    function addDeleteButtons() {
      Array.from(tbody.querySelectorAll('tr')).forEach(function(tr) {
        if (tr.querySelector('.row-del')) return;
        var lastCell = tr.cells[tr.cells.length - 1];
        if (!lastCell) return;
        var btn = document.createElement('button');
        btn.className = 'row-del';
        btn.textContent = '×';
        btn.title = 'Delete row';
        btn.hidden = true;
        btn.contentEditable = 'false';
        btn.addEventListener('click', function() { tr.remove(); });
        lastCell.appendChild(btn);
      });
    }

    function setEditing(on) {
      table.classList.toggle('editing', on);
      Array.from(tbody.querySelectorAll('td')).forEach(function(td) {
        td.contentEditable = on ? 'true' : 'false';
      });
      Array.from(tbody.querySelectorAll('.row-del')).forEach(function(b) {
        b.hidden = !on;
      });
      headerBtn.hidden = on;
      addBtn.hidden = !on;
      saveBtn.hidden = !on;
      cancelBtn.hidden = !on;
    }

    function rowsAsArray() {
      return Array.from(tbody.querySelectorAll('tr')).map(function(tr) {
        return Array.from(tr.cells).map(function(td) {
          var clone = td.cloneNode(true);
          var del = clone.querySelector('.row-del');
          if (del) del.remove();
          return clone.textContent.replace(/\s+/g, ' ').trim();
        });
      });
    }

    addDeleteButtons();

    headerBtn.addEventListener('click', function() {
      snapshot = tbody.innerHTML;
      setEditing(true);
      setStatus('', false);
    });

    cancelBtn.addEventListener('click', function() {
      if (snapshot != null) tbody.innerHTML = snapshot;
      addDeleteButtons();
      setEditing(false);
      setStatus('', false);
    });

    addBtn.addEventListener('click', function() {
      var tr = document.createElement('tr');
      for (var i = 0; i < ncols; i++) {
        var td = document.createElement('td');
        td.contentEditable = 'true';
        tr.appendChild(td);
      }
      tbody.appendChild(tr);
      addDeleteButtons();
      Array.from(tr.querySelectorAll('.row-del')).forEach(function(b) { b.hidden = false; });
      tr.cells[0].focus();
    });

    saveBtn.addEventListener('click', function() {
      if (!tripSlug) {
        setStatus('Cannot detect trip slug from URL', true);
        return;
      }
      var rows = rowsAsArray();
      saveBtn.disabled = true;
      cancelBtn.disabled = true;
      setStatus('Saving…', false);
      var url = '/api/save-section-table?trip=' + encodeURIComponent(tripSlug)
              + '&section=' + encodeURIComponent(sectionId);
      fetch(url, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({rows: rows})
      })
        .then(function(r) { return r.json().then(function(j) { return {ok: r.ok, j: j}; }); })
        .then(function(res) {
          if (!res.ok || !res.j.ok) {
            var err = (res.j && res.j.detail && res.j.detail.error) || 'save failed';
            setStatus('Error: ' + err, true);
            saveBtn.disabled = false;
            cancelBtn.disabled = false;
            return;
          }
          setStatus('Saved ✓ — reloading…', false);
          setTimeout(function() { location.reload(); }, 500);
        })
        .catch(function(e) {
          setStatus('Error: ' + e.message, true);
          saveBtn.disabled = false;
          cancelBtn.disabled = false;
        });
    });
  }
})();

// --- Generic per-section markdown editor ---
(function() {
  var slugMatch = location.pathname.match(/\/trips\/([^/]+)\//);
  var tripSlug = slugMatch ? slugMatch[1] : null;
  if (!tripSlug) return;

  Array.from(document.querySelectorAll('button[data-edit]')).forEach(function(btn) {
    if (btn.dataset.editMode === 'table') return;  // handled by table-editor IIFE
    var section = btn.dataset.edit;
    btn.addEventListener('click', function() { openEditor(section, btn); });
  });

  function statusEl(section) {
    return document.querySelector('[data-status="' + section + '"]');
  }
  function bodyEl(section) {
    return document.querySelector('[data-section-body="' + section + '"]');
  }
  function setStatus(section, text, isError) {
    var el = statusEl(section);
    if (!el) return;
    el.textContent = text || '';
    el.className = 'section-status' + (isError ? ' error' : '');
  }

  function openEditor(section, btn) {
    var body = bodyEl(section);
    if (!body) return;
    btn.disabled = true;
    setStatus(section, 'Loading…', false);
    fetch('/api/section?trip=' + encodeURIComponent(tripSlug)
          + '&section=' + encodeURIComponent(section))
      .then(function(r) { return r.json().then(function(j) { return {ok: r.ok, j: j}; }); })
      .then(function(res) {
        if (!res.ok || !res.j.ok) {
          var err = (res.j && res.j.detail && res.j.detail.error) || 'load failed';
          setStatus(section, 'Error: ' + err, true);
          btn.disabled = false;
          return;
        }
        renderEditor(section, body, btn, res.j.markdown || '');
      })
      .catch(function(e) {
        setStatus(section, 'Error: ' + e.message, true);
        btn.disabled = false;
      });
  }

  function renderEditor(section, body, editBtn, markdown) {
    var snapshot = body.innerHTML;
    var wrap = document.createElement('div');
    wrap.className = 'section-editor';
    var ta = document.createElement('textarea');
    ta.value = markdown;
    ta.spellcheck = false;
    var actions = document.createElement('div');
    actions.className = 'gear-edit-toolbar';
    actions.innerHTML =
      '<button class="gear-btn" data-act="save">Save</button>' +
      '<button class="gear-btn secondary" data-act="cancel">Cancel</button>';
    wrap.appendChild(ta);
    wrap.appendChild(actions);
    body.innerHTML = '';
    body.appendChild(wrap);
    setStatus(section, '', false);

    var saveBtn = actions.querySelector('[data-act=save]');
    var cancelBtn = actions.querySelector('[data-act=cancel]');

    cancelBtn.addEventListener('click', function() {
      body.innerHTML = snapshot;
      editBtn.disabled = false;
      setStatus(section, '', false);
    });

    saveBtn.addEventListener('click', function() {
      saveBtn.disabled = true;
      cancelBtn.disabled = true;
      setStatus(section, 'Saving…', false);
      fetch('/api/save-section?trip=' + encodeURIComponent(tripSlug)
            + '&section=' + encodeURIComponent(section), {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({markdown: ta.value})
      })
        .then(function(r) { return r.json().then(function(j) { return {ok: r.ok, j: j}; }); })
        .then(function(res) {
          if (!res.ok || !res.j.ok) {
            var err = (res.j && res.j.detail && res.j.detail.error) || 'save failed';
            setStatus(section, 'Error: ' + err, true);
            saveBtn.disabled = false;
            cancelBtn.disabled = false;
            return;
          }
          setStatus(section, 'Saved ✓ — reloading…', false);
          setTimeout(function() { location.reload(); }, 500);
        })
        .catch(function(e) {
          setStatus(section, 'Error: ' + e.message, true);
          saveBtn.disabled = false;
          cancelBtn.disabled = false;
        });
    });
  }
})();
"""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _stringify_dates(obj):
    """Recursively convert date/datetime values to ISO strings in parsed YAML."""
    if isinstance(obj, (datetime.date, datetime.datetime)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _stringify_dates(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_stringify_dates(item) for item in obj]
    return obj


def _slugify(text: str) -> str:
    """Lowercase, replace non-alphanumerics with hyphens, trim hyphens."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _load_park_info(park_slug: str) -> dict:
    """Look up park name + drive time from parks.json. Returns {} if not found."""
    repo_root = Path(__file__).parent
    parks_path = repo_root / "parks.json"
    if not parks_path.exists():
        return {}
    data = json.loads(parks_path.read_text(encoding="utf-8"))
    return data.get("parks", {}).get(park_slug, {})


def _render_header(fm: dict) -> str:
    park_info = _load_park_info(fm.get("park", ""))
    park_name = park_info.get("name", fm.get("park", "Trip"))
    drive = park_info.get("driveFromAjax", "")
    participants = ", ".join(fm.get("participants", []) or [])
    nights_rows = ""
    for night in fm.get("nights", []) or []:
        nights_rows += (
            f"<tr><td>{night.get('date', '')}</td>"
            f"<td>{night.get('site', '')}</td>"
            f"<td>{night.get('location', '')}</td></tr>"
        )
    nights_table = ""
    if nights_rows:
        nights_table = (
            '<table><thead><tr><th>Date</th><th>Site</th><th>Location</th>'
            f"</tr></thead><tbody>{nights_rows}</tbody></table>"
        )
    return (
        '<header class="trip-header">'
        '<button id="user-pill" class="user-pill unset" '
        'onclick="switchUser()" title="Click to set / change name">…</button>'
        f'<h1>{park_name} &middot; {fm.get("start_date", "")} → '
        f'{fm.get("end_date", "")}</h1>'
        '<div class="trip-meta">'
        f'<span><strong>Participants:</strong> {participants}</span>'
        + (f'<span><strong>Access:</strong> {fm.get("access_point", "")}</span>'
           if fm.get("access_point") else "")
        + (f'<span><strong>Drive from Ajax:</strong> {drive}</span>'
           if drive else "")
        + '</div>'
        + nights_table
        + '</header>'
    )

# ---------------------------------------------------------------------------
# Loading & rendering
# ---------------------------------------------------------------------------

def load_trip(trip_dir) -> dict:
    """Parse a trip directory.

    Returns dict with keys:
      frontmatter (dict from trip.md YAML),
      intro (str, markdown body of trip.md after frontmatter),
      itinerary, gear, food, packing, costs (str, markdown content),
      route_file (Path or None — prefers route.gpx over route.kml).
    """
    trip_dir = Path(trip_dir)
    trip_md_path = trip_dir / "trip.md"
    if not trip_md_path.exists():
        raise ValueError(f"{trip_md_path}: trip.md not found")
    trip_md = trip_md_path.read_text(encoding="utf-8")

    match = FRONTMATTER_RE.match(trip_md)
    if not match:
        raise ValueError(f"{trip_md_path}: missing YAML frontmatter")
    frontmatter = yaml.safe_load(match.group(1)) or {}
    frontmatter = _stringify_dates(frontmatter)
    intro = match.group(2).strip()

    sections = {}
    for name in SECTION_FILES:
        path = trip_dir / f"{name}.md"
        sections[name] = path.read_text(encoding="utf-8") if path.exists() else ""

    route_file = None
    for ext in ("gpx", "kml"):
        candidate = trip_dir / f"route.{ext}"
        if candidate.exists():
            route_file = candidate
            break

    return {
        "frontmatter": frontmatter,
        "intro": intro,
        "route_file": route_file,
        **sections,
    }


def render_section(md_text: str, section_id: str) -> str:
    """Render markdown to HTML. Task-list items become persistent checkboxes."""
    def replace(match):
        prefix = match.group("prefix")
        mark = match.group("mark")
        label = match.group("label")
        checked = "checked" if mark in "xX" else ""
        key = f"{section_id}--{_slugify(label)}"
        attrs = f'type="checkbox" data-cb-key="{escape(key)}"'
        if checked:
            attrs += " checked"
        return f"{prefix}<input {attrs}> {label}"

    processed = TASK_LINE_RE.sub(replace, md_text)
    return _md.markdown(processed, extensions=["tables", "fenced_code"])


def render_weather_section(park_slug: str, start_date: str, end_date: str) -> str:
    """Render the weather widget HTML using weather.get_weather()."""
    data = weather_provider(
        park_key=park_slug, start_date=start_date, end_date=end_date,
    )
    if data["source"] == "unavailable" or not data["days"]:
        return "<p>Weather data unavailable.</p>"

    label = "Forecast" if data["source"] == "forecast" else "Historical averages"
    rows = []
    for day in data["days"]:
        chance = ""
        if day.get("precip_chance") is not None:
            chance = f"{day['precip_chance']}% rain"
        elif day.get("precip_mm", 0) > 0:
            chance = f"~{day['precip_mm']}mm"
        rows.append(
            f"<tr><td>{day['date']}</td>"
            f"<td>{day.get('icon', '')} {day.get('description', '')}</td>"
            f"<td>{day['high']}&deg;C / {day['low']}&deg;C</td>"
            f"<td>{chance}</td></tr>"
        )

    return (
        f"<p><em>{label}</em></p>"
        '<table><thead><tr><th>Date</th><th>Conditions</th>'
        '<th>High / Low</th><th>Precip</th></tr></thead>'
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def render_route_section(trip) -> str:
    """Render the route map section.

    Three modes:
      1. trip['route_file'] set -> use the user-supplied GPX/KML (existing behavior).
      2. No route file but trip frontmatter has 'nights' + 'access_point' ->
         auto-route from cached OSM data.
      3. Neither -> return ''.

    Accepts either a trip dict (preferred, new) or a Path/None (legacy: route_file).
    """
    # Backward-compat: accept the old (route_file) signature where caller passed
    # a Path or None. If caller passes a dict, treat it as the trip dict.
    if trip is None:
        return ""
    if not isinstance(trip, dict):
        # Legacy path-only invocation.
        if trip is None:
            return ""
        data = _route_map.parse_route_file(str(trip))
        return _route_map.generate_map_section(data)

    route_file = trip.get("route_file")
    if route_file is not None:
        data = _route_map.parse_route_file(str(route_file))
        return _route_map.generate_map_section(data)

    fm = trip.get("frontmatter", {}) or {}
    nights = fm.get("nights") or []
    access_point = fm.get("access_point")
    if not (nights and access_point):
        return ""

    try:
        osm = _osm_data.load_killarney_features()
    except FileNotFoundError:
        return ""

    # Optional GPX library — used when a real trace exists for a lake-pair
    # leg. Falls back to OSM portage graph otherwise.
    import gpx_library as _gpx_library
    library = _gpx_library.load_library_index(
        Path(__file__).parent / "routes" / "killarney" / "library"
    )

    route = _route_engine.build_route(
        nights=nights, access_point=access_point, osm=osm, library=library,
    )
    return _render_auto_route(route)


def _render_auto_route(route: dict) -> str:
    """Render the OSM-driven route section: map + per-day estimates table."""
    days = _route_engine.build_day_estimates(route["segments"])

    # Build a route_map-compatible structure to pass to generate_map_section.
    tracks = []
    for seg in route["segments"]:
        if not seg["geometry"]:
            continue
        # Each segment becomes a track; route_map.py will color-cycle them.
        track_name = f"{seg['from']} → {seg['to']} ({seg['kind']})"
        tracks.append({
            "name": track_name,
            "points": [tuple(pt) for pt in seg["geometry"]],
        })
    # Markers (access point + per-night site centroids) become Leaflet pins.
    waypoints = [
        {"lat": m["lat"], "lon": m["lon"], "name": m["label"], "desc": ""}
        for m in route.get("markers", [])
    ]
    # Add portage entry/exit pins for each portage actually used in the route.
    for seg in route["segments"]:
        if seg["kind"] != "portage" or len(seg["geometry"]) < 2:
            continue
        entry = seg["geometry"][0]
        exit_ = seg["geometry"][-1]
        dist = seg["distance_km"]
        waypoints.append({
            "lat": entry[0], "lon": entry[1],
            "name": f"Portage take-out → {seg['to']}", "desc": f"{dist} km",
        })
        waypoints.append({
            "lat": exit_[0], "lon": exit_[1],
            "name": f"Portage put-in ← {seg['from']}", "desc": f"{dist} km",
        })
    map_html = _route_map.generate_map_section({
        "waypoints": waypoints, "tracks": tracks, "source": "auto",
    })

    # Per-day estimates table.
    rows = []
    total_paddle = 0.0
    total_portage = 0.0
    total_minutes = 0
    for day in days:
        approx_marker = " ⚠" if day["approx"] else ""
        portage_cell = (
            "(approx)" if day["approx"] and day["portage_km"] == 0
            else f"{day['portage_km']} km"
        )
        rows.append(
            f"<tr><td>{day['day']}</td>"
            f"<td>{day['label']}{approx_marker}</td>"
            f"<td>{day['paddle_km']} km</td>"
            f"<td>{portage_cell}</td>"
            f"<td>{day['human_time']}</td></tr>"
        )
        total_paddle += day["paddle_km"]
        total_portage += day["portage_km"]
        total_minutes += day["minutes"]

    rows.append(
        f"<tr><td><strong>Total</strong></td><td></td>"
        f"<td><strong>{round(total_paddle, 1)} km</strong></td>"
        f"<td><strong>{round(total_portage, 1)} km</strong></td>"
        f"<td><strong>{_route_engine.format_human_time(total_minutes)}</strong></td></tr>"
    )

    warnings_html = ""
    if route.get("warnings"):
        items = "".join(f"<li>{w}</li>" for w in route["warnings"])
        warnings_html = f'<div class="warnings"><ul>{items}</ul></div>'

    table_html = (
        "<table><thead><tr><th>Day</th><th>Leg</th>"
        "<th>Paddle</th><th>Portage</th><th>Est. time</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )

    return (
        f"{warnings_html}"
        f"{map_html}"
        f"{table_html}"
    )

# ---------------------------------------------------------------------------
# Top-level orchestration
# ---------------------------------------------------------------------------

EDITABLE_SECTIONS = ("intro", "itinerary", "gear", "food", "packing", "costs")
# Sections whose Edit button opens the in-place table editor instead of the
# generic markdown textarea. Must match TABLE_SECTIONS in app/services/trips.py.
TABLE_EDIT_SECTIONS = ("gear", "costs")


def _wrap_section(
    section_id: str, title: str, body_html: str, edit_mode: str | None,
) -> str:
    """Emit a section with a header bar (title + optional Edit button) + body.

    edit_mode:
      None      — read-only (route, weather)
      'markdown' — header Edit button opens the markdown textarea editor
      'table'   — header Edit button opens the in-place table row editor
    """
    if edit_mode in ("markdown", "table"):
        actions = (
            '<div class="section-actions">'
            f'<button class="section-btn" data-edit="{section_id}" '
            f'data-edit-mode="{edit_mode}">Edit</button>'
            f'<span class="section-status" data-status="{section_id}"></span>'
            '</div>'
        )
    else:
        actions = ""
    return (
        f'<section id="{section_id}">'
        '<div class="section-header">'
        f'<h2>{title}</h2>'
        f'{actions}'
        '</div>'
        f'<div class="section-body" data-section-body="{section_id}">{body_html}</div>'
        '</section>'
    )


def _edit_mode(section_id: str) -> str:
    return "table" if section_id in TABLE_EDIT_SECTIONS else "markdown"


def build_html(trip_dir) -> str:
    """Build the full self-contained HTML page for a trip directory."""
    trip = load_trip(trip_dir)
    fm = trip["frontmatter"]

    sections_html = []
    sections_html.append(_wrap_section(
        "intro", "Overview",
        render_section(trip["intro"], "intro") if trip["intro"] else "",
        edit_mode=_edit_mode("intro"),
    ))
    sections_html.append(_wrap_section(
        "itinerary", "Itinerary",
        render_section(trip["itinerary"], "itinerary"),
        edit_mode=_edit_mode("itinerary"),
    ))
    route_html = render_route_section(trip)
    if route_html:
        sections_html.append(_wrap_section("route", "Route", route_html, edit_mode=None))
    weather_html = render_weather_section(
        fm.get("park", ""), fm.get("start_date", ""), fm.get("end_date", ""),
    )
    if weather_html:
        sections_html.append(_wrap_section(
            "weather", "Weather", weather_html, edit_mode=None,
        ))
    sections_html.append(_wrap_section(
        "gear", "Gear", render_section(trip["gear"], "gear"),
        edit_mode=_edit_mode("gear"),
    ))
    sections_html.append(_wrap_section(
        "food", "Food", render_section(trip["food"], "food"),
        edit_mode=_edit_mode("food"),
    ))
    sections_html.append(_wrap_section(
        "packing", "Packing", render_section(trip["packing"], "packing"),
        edit_mode=_edit_mode("packing"),
    ))
    sections_html.append(_wrap_section(
        "costs", "Costs", render_section(trip["costs"], "costs"),
        edit_mode=_edit_mode("costs"),
    ))

    body = _render_header(fm) + "\n".join(s for s in sections_html if s)
    title = (
        f'{_load_park_info(fm.get("park", "")).get("name", "Trip")} '
        f'{fm.get("start_date", "")}'
    )
    return (
        '<!DOCTYPE html><html lang="en"><head>'
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>{title}</title>'
        f'<style>{_PAGE_CSS}</style>'
        '</head><body>'
        f'{body}'
        f'<script>{_PAGE_JS}</script>'
        '</body></html>'
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trip_dir", help="Path to trip directory (contains trip.md)")
    parser.add_argument(
        "--refresh-osm", action="store_true",
        help="Re-fetch the Killarney OSM cache from Overpass before rendering.",
    )
    parser.add_argument(
        "--refresh-library", action="store_true",
        help="Re-segment all GPX in routes/killarney/library/ and rewrite "
             "index.json before rendering.",
    )
    args = parser.parse_args(argv)

    if args.refresh_osm:
        _osm_data.refresh_killarney_cache()

    if args.refresh_library:
        import gpx_library as _gpx_library
        osm = _osm_data.load_killarney_features()
        library_dir = Path(__file__).parent / "routes" / "killarney" / "library"
        out = _gpx_library.write_library_index(library_dir, osm)
        idx = _gpx_library.load_library_index(library_dir)
        trusted = [c for c in idx["connectors"] if c.get("trusted")]
        rejected = [c for c in idx["connectors"] if not c.get("trusted")]
        print(f"Wrote {len(idx['connectors'])} connectors to {out}")
        print(f"  trusted: {len(trusted)}, rejected: {len(rejected)}")
        for c in rejected:
            print(f"  REJECTED  {c['lake_a']} -> {c['lake_b']}  "
                  f"({c['source']})  reason: {c['trust_reason']}")

    trip_dir = Path(args.trip_dir)
    html = build_html(trip_dir)
    out_path = trip_dir / "trip.html"
    out_path.write_text(html, encoding="utf-8")
    print(f"Wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
