function toggleNewTrip() {
  var s = document.getElementById('new-trip');
  s.hidden = !s.hidden;
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
    mode: f.mode.value,
  };
  try {
    var r = await fetch('/api/trips', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body),
    });
    var j = await r.json();
    if (r.ok && j.ok) {
      status.textContent = 'Created ' + j.slug + ' — navigating…';
      setTimeout(function(){ window.location.href = '/trip/' + encodeURIComponent(j.slug); }, 800);
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
