(function() {
  const sectionEl = document.querySelector('[data-section="route"]');
  if (!sectionEl) return;
  const slug = document.body.dataset.tripSlug;
  const btn = sectionEl.querySelector('.edit-btn');
  if (!btn) return;

  btn.addEventListener('click', async () => {
    const r = await fetch(`/api/trips/${slug}/routes`);
    const routes = await r.json();
    const wrap = document.createElement('div');
    wrap.innerHTML = `<p class="hint">Reorder, rename, or remove waypoints.
      To draw new lines, use <a href="/overlay/?trip=${slug}">the overlay</a>.</p>
      <div class="routes-edit"></div>`;
    const routesDiv = wrap.querySelector('.routes-edit');
    routes.forEach((route, i) => {
      const block = document.createElement('div');
      block.className = 'route-edit';
      block.dataset.index = i;
      block.innerHTML = `<h4><input class="r-name" value="${route.name||''}"></h4>
        <ul class="waypoints"></ul>
        <button class="btn btn-ghost rm-route">remove this route</button>`;
      const ul = block.querySelector('.waypoints');
      (route.waypoints || []).forEach((w, j) => {
        const li = document.createElement('li');
        li.draggable = true;
        li.dataset.index = j;
        li.innerHTML = `<span class="drag">⋮⋮</span>
          <input class="w-name" value="${w.name||''}">
          <span class="coords">${w.lat?.toFixed(4)}, ${w.lng?.toFixed(4)}</span>
          <button class="btn btn-ghost rm-wp">×</button>`;
        li.querySelector('.rm-wp').onclick = () => li.remove();
        li.addEventListener('dragstart', e => {
          e.dataTransfer.setData('text/plain', j);
        });
        li.addEventListener('dragover', e => e.preventDefault());
        li.addEventListener('drop', e => {
          e.preventDefault();
          const from = Number(e.dataTransfer.getData('text/plain'));
          const items = Array.from(ul.children);
          ul.insertBefore(items[from], li);
        });
        ul.appendChild(li);
      });
      block.querySelector('.rm-route').onclick = () => block.remove();
      routesDiv.appendChild(block);
    });

    const body = sectionEl.querySelector('.section-body');
    const original = body.innerHTML;
    body.innerHTML = '';
    body.appendChild(wrap);
    const toolbar = document.createElement('div');
    toolbar.className = 'edit-toolbar';
    toolbar.innerHTML = `<button class="btn save">Save</button>
      <button class="btn btn-ghost cancel">Cancel</button>`;
    body.appendChild(toolbar);
    toolbar.querySelector('.cancel').onclick = () => { body.innerHTML = original; };
    toolbar.querySelector('.save').onclick = async () => {
      const out = [];
      routesDiv.querySelectorAll('.route-edit').forEach(block => {
        const i = Number(block.dataset.index);
        const orig = routes[i];
        const waypoints = [];
        block.querySelectorAll('.waypoints li').forEach(li => {
          const j = Number(li.dataset.index);
          const origWp = (orig.waypoints || [])[j];
          waypoints.push({...origWp, name: li.querySelector('.w-name').value});
        });
        out.push({...orig, name: block.querySelector('.r-name').value, waypoints});
      });
      const resp = await fetch(`/api/trips/${slug}/routes`, {
        method: 'PUT', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(out),
      });
      if (!resp.ok) { alert('save failed: ' + await resp.text()); return; }
      window.location.reload();
    };
  });
})();
