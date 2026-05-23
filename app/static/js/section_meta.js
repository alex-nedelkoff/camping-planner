(function() {
  const headerEl = document.querySelector('.trip-hero');
  if (!headerEl) return;
  const slug = document.body.dataset.tripSlug;

  const btn = document.createElement('button');
  btn.className = 'btn btn-ghost edit-btn';
  btn.textContent = 'Edit trip details';
  btn.style.cssText = 'position:absolute; top:1rem; right:1rem;';
  headerEl.style.position = 'relative';
  headerEl.appendChild(btn);

  btn.addEventListener('click', async () => {
    const trip = await SectionEditor.loadTrip(slug);
    const form = document.createElement('form');
    form.innerHTML = `
      <label>Park <input name="park" value="${trip.park||''}"></label>
      <label>Start <input type="date" name="start" value="${trip.dates.start}"></label>
      <label>End <input type="date" name="end" value="${trip.dates.end}"></label>
      <label>Access point <input name="access_point" value="${trip.access_point||''}"></label>
      <label>Participants (comma-sep) <input name="participants" value="${(trip.participants||[]).join(', ')}"></label>
      <h3>Nights</h3>
      <table class="nights-edit"><thead>
        <tr><th>Date</th><th>Site</th><th>Location</th><th>GPS lat</th><th>GPS lng</th><th></th></tr>
      </thead><tbody></tbody></table>
      <button type="button" class="btn btn-ghost add-night">+ night</button>
      <div class="edit-toolbar">
        <button type="submit" class="btn">Save</button>
        <button type="button" class="btn btn-ghost cancel">Cancel</button>
      </div>`;
    const tbody = form.querySelector('.nights-edit tbody');
    function addNight(n = {date:'', site:'', location:'', gps:null}) {
      const tr = document.createElement('tr');
      const lat = n.gps ? n.gps[0] : '';
      const lng = n.gps ? n.gps[1] : '';
      tr.innerHTML = `<td><input type="date" class="n-date" value="${n.date||''}"></td>
        <td><input class="n-site" value="${n.site||''}"></td>
        <td><input class="n-loc" value="${n.location||''}"></td>
        <td><input class="n-lat" value="${lat}"></td>
        <td><input class="n-lng" value="${lng}"></td>
        <td><button type="button" class="btn btn-ghost rm">×</button></td>`;
      tr.querySelector('.rm').onclick = () => tr.remove();
      tbody.appendChild(tr);
    }
    (trip.nights||[]).forEach(addNight);
    form.querySelector('.add-night').onclick = () => addNight();

    const overlay = document.createElement('div');
    overlay.className = 'meta-edit-overlay';
    overlay.appendChild(form);
    document.body.appendChild(overlay);

    form.querySelector('.cancel').onclick = () => overlay.remove();
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const nights = [];
      tbody.querySelectorAll('tr').forEach(tr => {
        const lat = tr.querySelector('.n-lat').value;
        const lng = tr.querySelector('.n-lng').value;
        nights.push({
          date: tr.querySelector('.n-date').value,
          site: tr.querySelector('.n-site').value,
          location: tr.querySelector('.n-loc').value,
          gps: (lat && lng) ? [Number(lat), Number(lng)] : null,
        });
      });
      const fd = new FormData(form);
      const body = {
        park: fd.get('park'),
        dates: {start: fd.get('start'), end: fd.get('end')},
        access_point: fd.get('access_point'),
        participants: fd.get('participants').split(',').map(s => s.trim()).filter(Boolean),
        nights,
      };
      const r = await fetch(`/api/trips/${slug}/meta`, {
        method: 'PATCH',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body),
      });
      if (!r.ok) { alert('save failed: ' + await r.text()); return; }
      window.location.reload();
    });
  });
})();
