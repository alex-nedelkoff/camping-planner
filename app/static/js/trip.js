/* Trip-pane behaviour: checklist sync, gear table editor, per-section editor.
   The SPA calls initTripPane(root, slug) each time it swaps in a new trip. */

(function (global) {
  'use strict';

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  // -------------------------------------------------------------------------
  // Checklist sync — one input[type=checkbox][data-cb-key] = one row in DB.
  // Server is source of truth; localStorage is offline cache namespaced per-user.
  // -------------------------------------------------------------------------
  function initChecklist(root, slug, currentUser) {
    var boxes = root.querySelectorAll('input[type=checkbox][data-cb-key]');
    if (!boxes.length) return Promise.resolve();

    function lkey(cbKey) { return 'cb:' + (currentUser || '') + ':' + cbKey; }

    boxes.forEach(function (cb) {
      var saved = localStorage.getItem(lkey(cb.dataset.cbKey));
      if (saved === '1') cb.checked = true;
      else if (saved === '0') cb.checked = false;
      cb.addEventListener('change', function () {
        localStorage.setItem(lkey(cb.dataset.cbKey), cb.checked ? '1' : '0');
        if (!slug) return;
        fetch('/api/checklist?trip=' + encodeURIComponent(slug), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ key: cb.dataset.cbKey, checked: cb.checked }),
        }).catch(function () { /* offline */ });
      });
    });

    if (!slug) return Promise.resolve();
    return fetch('/api/checklist?trip=' + encodeURIComponent(slug))
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (j) {
        if (!j || !j.ok || !j.state) return;
        boxes.forEach(function (cb) {
          if (Object.prototype.hasOwnProperty.call(j.state, cb.dataset.cbKey)) {
            cb.checked = !!j.state[cb.dataset.cbKey];
            localStorage.setItem(lkey(cb.dataset.cbKey), cb.checked ? '1' : '0');
          }
        });
      })
      .catch(function () { /* offline */ });
  }

  // -------------------------------------------------------------------------
  // Gear table editor: contenteditable rows, +/- row buttons, save → markdown.
  // -------------------------------------------------------------------------
  function initGearEditor(root, slug, onSaved) {
    var section = root.querySelector('#gear');
    if (!section) return;
    var table = section.querySelector('table');
    if (!table) return;
    var tbody = table.querySelector('tbody');
    if (!tbody) return;

    var ncols = 0;
    var firstRow = tbody.querySelector('tr');
    if (firstRow) ncols = firstRow.cells.length;
    if (!ncols) {
      var theadRow = table.querySelector('thead tr');
      if (theadRow) ncols = theadRow.cells.length;
    }
    if (!ncols) return;

    var toolbar = document.createElement('div');
    toolbar.className = 'gear-edit-toolbar';
    toolbar.innerHTML =
      '<button class="gear-btn" data-act="edit">Edit gear</button>' +
      '<button class="gear-btn" data-act="add" hidden>+ Add row</button>' +
      '<button class="gear-btn" data-act="save" hidden>Save</button>' +
      '<button class="gear-btn secondary" data-act="cancel" hidden>Cancel</button>' +
      '<span class="gear-status"></span>';
    table.after(toolbar);

    var editBtn = toolbar.querySelector('[data-act=edit]');
    var addBtn = toolbar.querySelector('[data-act=add]');
    var saveBtn = toolbar.querySelector('[data-act=save]');
    var cancelBtn = toolbar.querySelector('[data-act=cancel]');
    var status = toolbar.querySelector('.gear-status');
    var snapshot = null;

    function addDeleteButtons() {
      Array.from(tbody.querySelectorAll('tr')).forEach(function (tr) {
        if (tr.querySelector('.row-del')) return;
        var lastCell = tr.cells[tr.cells.length - 1];
        if (!lastCell) return;
        var btn = document.createElement('button');
        btn.className = 'row-del';
        btn.textContent = '×';
        btn.title = 'Delete row';
        btn.hidden = true;
        btn.contentEditable = 'false';
        btn.addEventListener('click', function () { tr.remove(); });
        lastCell.appendChild(btn);
      });
    }

    function setEditing(on) {
      table.classList.toggle('editing', on);
      Array.from(tbody.querySelectorAll('td')).forEach(function (td) {
        td.contentEditable = on ? 'true' : 'false';
      });
      Array.from(tbody.querySelectorAll('.row-del')).forEach(function (b) {
        b.hidden = !on;
      });
      editBtn.hidden = on;
      addBtn.hidden = !on;
      saveBtn.hidden = !on;
      cancelBtn.hidden = !on;
    }

    function rowsAsArray() {
      return Array.from(tbody.querySelectorAll('tr')).map(function (tr) {
        return Array.from(tr.cells).map(function (td) {
          var clone = td.cloneNode(true);
          var del = clone.querySelector('.row-del');
          if (del) del.remove();
          return clone.textContent.replace(/\s+/g, ' ').trim();
        });
      });
    }

    addDeleteButtons();

    editBtn.addEventListener('click', function () {
      snapshot = tbody.innerHTML;
      setEditing(true);
      status.textContent = '';
      status.className = 'gear-status';
    });

    cancelBtn.addEventListener('click', function () {
      if (snapshot != null) tbody.innerHTML = snapshot;
      addDeleteButtons();
      setEditing(false);
      status.textContent = '';
    });

    addBtn.addEventListener('click', function () {
      var tr = document.createElement('tr');
      for (var i = 0; i < ncols; i++) {
        var td = document.createElement('td');
        td.contentEditable = 'true';
        tr.appendChild(td);
      }
      tbody.appendChild(tr);
      addDeleteButtons();
      Array.from(tr.querySelectorAll('.row-del')).forEach(function (b) { b.hidden = false; });
      tr.cells[0].focus();
    });

    saveBtn.addEventListener('click', async function () {
      if (!slug) {
        status.textContent = 'No trip slug';
        status.className = 'gear-status error';
        return;
      }
      var rows = rowsAsArray();
      saveBtn.disabled = true;
      cancelBtn.disabled = true;
      status.textContent = 'Saving…';
      status.className = 'gear-status';
      try {
        var r = await fetch('/api/save-gear?trip=' + encodeURIComponent(slug), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ rows: rows }),
        });
        var j = await r.json();
        if (j.ok) {
          status.textContent = 'Saved ✓';
          if (typeof onSaved === 'function') onSaved();
        } else {
          var err = (j && j.detail && j.detail.error) || j.error || 'unknown';
          status.textContent = 'Error: ' + err;
          status.className = 'gear-status error';
          saveBtn.disabled = false;
          cancelBtn.disabled = false;
        }
      } catch (e) {
        status.textContent = 'Error: ' + e.message;
        status.className = 'gear-status error';
        saveBtn.disabled = false;
        cancelBtn.disabled = false;
      }
    });
  }

  // -------------------------------------------------------------------------
  // Section markdown editor: per-section "Edit" button swaps the body for a
  // textarea bound to /api/section + /api/save-section.
  // -------------------------------------------------------------------------
  function initSectionEditors(root, slug, onSaved) {
    if (!slug) return;
    var buttons = root.querySelectorAll('button.section-btn[data-edit]');
    buttons.forEach(function (btn) {
      btn.addEventListener('click', function () {
        var sectionId = btn.getAttribute('data-edit');
        var body = root.querySelector('[data-section-body="' + sectionId + '"]');
        var status = root.querySelector('[data-status="' + sectionId + '"]');
        if (!body) return;
        var snapshot = body.innerHTML;
        btn.disabled = true;
        if (status) { status.textContent = 'Loading…'; status.className = 'section-status'; }

        fetch('/api/section?trip=' + encodeURIComponent(slug)
              + '&section=' + encodeURIComponent(sectionId))
          .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
          .then(function (res) {
            if (!res.ok || !res.j.ok) {
              var err = (res.j && res.j.detail && res.j.detail.error) || 'load failed';
              if (status) { status.textContent = 'Error: ' + err; status.className = 'section-status error'; }
              btn.disabled = false;
              return;
            }
            renderEditor(sectionId, res.j.markdown, body, btn, status, snapshot);
          })
          .catch(function (e) {
            if (status) { status.textContent = 'Error: ' + e.message; status.className = 'section-status error'; }
            btn.disabled = false;
          });
      });
    });

    function renderEditor(sectionId, markdown, body, btn, status, snapshot) {
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
      if (status) { status.textContent = ''; status.className = 'section-status'; }

      var saveBtn = actions.querySelector('[data-act=save]');
      var cancelBtn = actions.querySelector('[data-act=cancel]');

      cancelBtn.addEventListener('click', function () {
        body.innerHTML = snapshot;
        btn.disabled = false;
        if (status) { status.textContent = ''; status.className = 'section-status'; }
      });

      saveBtn.addEventListener('click', function () {
        saveBtn.disabled = true;
        cancelBtn.disabled = true;
        if (status) { status.textContent = 'Saving…'; status.className = 'section-status'; }
        fetch('/api/save-section?trip=' + encodeURIComponent(slug)
              + '&section=' + encodeURIComponent(sectionId), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ markdown: ta.value }),
        })
          .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
          .then(function (res) {
            if (!res.ok || !res.j.ok) {
              var err = (res.j && res.j.detail && res.j.detail.error) || 'save failed';
              if (status) { status.textContent = 'Error: ' + err; status.className = 'section-status error'; }
              saveBtn.disabled = false;
              cancelBtn.disabled = false;
              return;
            }
            if (status) { status.textContent = 'Saved ✓'; status.className = 'section-status'; }
            if (typeof onSaved === 'function') onSaved();
          })
          .catch(function (e) {
            if (status) { status.textContent = 'Error: ' + e.message; status.className = 'section-status error'; }
            saveBtn.disabled = false;
            cancelBtn.disabled = false;
          });
      });
    }
  }

  // -------------------------------------------------------------------------
  // <script> tags inside fetched HTML do NOT execute when assigned via
  // innerHTML. The route map's Leaflet bootstrap lives in inline scripts, so
  // we re-clone & insert each one to force execution.
  // -------------------------------------------------------------------------
  function runEmbeddedScripts(root) {
    var scripts = Array.from(root.querySelectorAll('script'));
    scripts.forEach(function (old) {
      var s = document.createElement('script');
      Array.from(old.attributes).forEach(function (a) { s.setAttribute(a.name, a.value); });
      s.text = old.text || old.textContent || '';
      old.parentNode.replaceChild(s, old);
    });
  }

  global.TripPane = {
    init: function (root, slug, currentUser, onSaved) {
      runEmbeddedScripts(root);
      initChecklist(root, slug, currentUser);
      initGearEditor(root, slug, onSaved);
      initSectionEditors(root, slug, onSaved);
    },
    escapeHtml: escapeHtml,
  };
})(window);
