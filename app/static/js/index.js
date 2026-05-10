function toggleNewTrip() {
  var s = document.getElementById('new-trip');
  s.hidden = !s.hidden;
}

// --- Auto-fill end date = start + 5 days, only when end is empty.
// Wired on every form on the index that pairs a `start` and `end` date input.
function plusDaysISO(iso, days) {
  var d = new Date(iso + 'T00:00:00');
  if (isNaN(d.getTime())) return '';
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}

function wireAutoEnd(form) {
  if (!form) return;
  var start = form.querySelector('input[name=start]');
  var end = form.querySelector('input[name=end]');
  if (!start || !end) return;
  start.addEventListener('change', function() {
    if (end.value || !start.value) return;
    var bumped = plusDaysISO(start.value, 5);
    if (bumped) end.value = bumped;
  });
}

document.addEventListener('DOMContentLoaded', function() {
  Array.from(document.querySelectorAll('form')).forEach(wireAutoEnd);
});

async function rebuild(btn, name) {
  var orig = btn.textContent;
  btn.disabled = true;
  btn.textContent = 'Rebuilding…';
  try {
    var r = await fetch('/api/rebuild?trip=' + encodeURIComponent(name), {method: 'POST'});
    var j = await r.json();
    btn.textContent = j.ok ? 'Rebuilt ✓' : 'Failed';
  } catch (e) {
    btn.textContent = 'Error';
  }
  setTimeout(function() { btn.textContent = orig; btn.disabled = false; }, 2000);
}

async function createTrip(ev) {
  ev.preventDefault();
  var f = ev.target;
  var status = document.getElementById('new-trip-status');
  status.className = 'status';
  status.textContent = 'Creating…';
  var body = {
    park: f.park.value,
    start: f.start.value,
    end: f.end.value,
    participants: f.participants.value.split(',').map(function(s){return s.trim();}).filter(Boolean),
  };
  try {
    var r = await fetch('/api/new-trip', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body),
    });
    var j = await r.json();
    if (r.ok && j.ok) {
      status.textContent = 'Created ' + j.trip_dir + ' — reloading…';
      setTimeout(function(){ location.reload(); }, 800);
    } else {
      status.className = 'status error';
      var err = (j && j.detail && j.detail.error) || (j && j.error) || 'unknown';
      status.textContent = 'Error: ' + err;
    }
  } catch (e) {
    status.className = 'status error';
    status.textContent = 'Error: ' + e.message;
  }
}

async function checkAvail(ev) {
  ev.preventDefault();
  var f = ev.target;
  var btn = document.getElementById('avail-btn');
  var out = document.getElementById('avail-results');
  btn.disabled = true;
  btn.textContent = 'Checking…';
  out.innerHTML = '<p>Checking — this can take 5–15 seconds…</p>';
  var params = new URLSearchParams({park: f.park.value, start: f.start.value, end: f.end.value});
  try {
    var r = await fetch('/api/availability?' + params.toString());
    var j = await r.json();
    if (r.ok && j.ok) {
      var html = '<h3>' + escapeHtml(j.park_name) + ': ' + j.total_available + ' site(s) available</h3>';
      var keys = Object.keys(j.campgrounds || {});
      if (keys.length) {
        html += '<table><thead><tr><th>Campground</th><th>Available / Total</th></tr></thead><tbody>';
        keys.forEach(function(name) {
          var info = j.campgrounds[name];
          html += '<tr><td>' + escapeHtml(name) + '</td><td>' + info.available + ' / ' + info.total + '</td></tr>';
        });
        html += '</tbody></table>';
      }
      out.innerHTML = html;
    } else {
      var err = (j && j.detail && j.detail.error) || (j && j.error) || 'unknown';
      out.innerHTML = '<p class="status error">Error: ' + escapeHtml(err) + '</p>';
    }
  } catch (e) {
    out.innerHTML = '<p class="status error">Error: ' + escapeHtml(e.message) + '</p>';
  } finally {
    btn.disabled = false;
    btn.textContent = 'Check';
  }
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, function(c) {
    return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];
  });
}

// --- Identity (cookie-based, no password) ---

async function loadUser() {
  try {
    var r = await fetch('/api/whoami');
    var j = await r.json();
    paintUser(j.user || '');
    if (!j.user) promptForName();
  } catch (e) { /* offline — leave pill as-is */ }
}

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

async function setUser(name) {
  var r = await fetch('/api/whoami', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({user: name})
  });
  var j = await r.json();
  if (r.ok) paintUser(j.user || '');
  return r.ok;
}

function promptForName() {
  var name = prompt('Whose checklist is this? (your first name is fine)');
  if (name && name.trim()) setUser(name.trim());
}

function switchUser() {
  var current = (document.getElementById('user-pill') || {}).textContent || '';
  var suggested = current.indexOf('Hi, ') === 0 ? current.slice(4) : '';
  var name = prompt('Switch to whom?', suggested);
  if (name === null) return;
  if (!name.trim()) {
    fetch('/api/whoami', {method: 'DELETE'}).then(function(){ paintUser(''); });
  } else {
    setUser(name.trim());
  }
}

document.addEventListener('DOMContentLoaded', loadUser);
