/**
 * Shared section edit-mode helper. Each section module calls:
 *   SectionEditor.setup({ name, readEl, renderEdit, collectEdit, slug })
 *
 * renderEdit is invoked with (currentSectionData, fullTrip). Modules that
 * only need their own section data can ignore the second argument.
 */
window.SectionEditor = (function() {
  async function loadTrip(slug) {
    const r = await fetch(`/api/trips/${slug}`);
    if (!r.ok) throw new Error('load failed');
    return r.json();
  }

  async function saveSection(slug, name, data) {
    const r = await fetch(`/api/trips/${slug}/section/${name}`, {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(data),
    });
    if (!r.ok) {
      const err = await r.text();
      throw new Error(`save failed: ${r.status} ${err}`);
    }
    return r.json();
  }

  function setup(opts) {
    const editBtn = opts.readEl.querySelector('.edit-btn');
    if (!editBtn) return;
    editBtn.addEventListener('click', async () => {
      const trip = await loadTrip(opts.slug);
      const currentData = trip[opts.name];
      const editView = opts.renderEdit(currentData, trip);
      const bodyEl = opts.readEl.querySelector('.section-body');
      const original = bodyEl.innerHTML;

      opts.readEl.classList.add('editing');
      bodyEl.innerHTML = '';
      bodyEl.appendChild(editView);

      const saveBtn = document.createElement('button');
      saveBtn.className = 'btn btn-primary'; saveBtn.textContent = 'Save';
      const cancelBtn = document.createElement('button');
      cancelBtn.className = 'btn btn-ghost'; cancelBtn.textContent = 'Cancel';
      const toolbar = document.createElement('div');
      toolbar.className = 'edit-toolbar';
      toolbar.append(saveBtn, cancelBtn);
      bodyEl.appendChild(toolbar);

      const exitEdit = () => {
        opts.readEl.classList.remove('editing');
      };

      saveBtn.onclick = async () => {
        saveBtn.disabled = true;
        saveBtn.textContent = 'Saving…';
        try {
          const newData = opts.collectEdit(editView);
          await saveSection(opts.slug, opts.name, newData);
          window.location.reload();
        } catch (e) {
          alert(e.message);
          saveBtn.disabled = false;
          saveBtn.textContent = 'Save';
        }
      };
      cancelBtn.onclick = () => {
        bodyEl.innerHTML = original;
        exitEdit();
      };
    });
  }

  return { setup, loadTrip, saveSection };
})();

// Generic helper for "Refresh" buttons (weather, route): POST + reload.
window.refreshSection = async function(btn, url) {
  const original = btn.textContent;
  btn.textContent = 'Refreshing…';
  btn.disabled = true;
  try {
    const r = await fetch(url, {method: 'POST'});
    if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
    window.location.reload();
  } catch (e) {
    alert('Refresh failed: ' + e.message);
    btn.textContent = original;
    btn.disabled = false;
  }
};
