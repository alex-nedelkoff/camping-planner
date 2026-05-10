/* Trip-page gear plan. Mounted by trip.js / index.js when a section has kind=gear-plan. */
(function (global) {
  'use strict';

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  function pillColor(category) {
    if (!category) return '#9ca3af';
    const palette = ['#2563eb', '#16a34a', '#f59e0b', '#dc2626', '#7c3aed',
                     '#0891b2', '#db2777', '#65a30d', '#ea580c', '#475569',
                     '#9333ea', '#0d9488'];
    let h = 0;
    for (let i = 0; i < category.length; i++) h = (h * 31 + category.charCodeAt(i)) >>> 0;
    return palette[h % palette.length];
  }

  function init(sectionEl, slug, payload) {
    let plan = (payload && payload.plan) || { items: [], participants: [], legacy_body: '' };
    let totals = (payload && payload.totals) || { items: [], by_who: {}, trip_g: 0, unknown_count: 0 };
    let catalog = { items: [], categories: [] };

    function recomputeTotals() {
      const byId = Object.fromEntries(catalog.items.map(it => [it.id, it]));
      const out = [];
      const byWho = {};
      let tripG = 0;
      let unknownCount = 0;
      for (const row of plan.items) {
        const item = byId[row.item_id];
        const unknown_item = !item;
        const name = unknown_item ? null : item.name;
        const category = unknown_item ? null : item.category;
        const catalogWeight = unknown_item ? null : (item.weight_g ?? null);
        const override = row.override_weight_g ?? null;
        const eachWeight = override !== null ? override : catalogWeight;
        const qty = parseInt(row.qty, 10) || 0;
        let total = null;
        const unknown_weight = eachWeight === null;
        if (eachWeight === null) {
          unknownCount += 1;
        } else {
          total = eachWeight * qty;
          tripG += total;
          const who = row.who || 'shared';
          byWho[who] = (byWho[who] || 0) + total;
        }
        out.push({ ...row, name, category, weight_g_each: eachWeight,
                   weight_g_total: total, unknown_weight, unknown_item });
      }
      totals = { items: out, by_who: byWho, trip_g: tripG, unknown_count: unknownCount };
    }

    function renderHeader() {
      const tripG = totals.trip_g;
      const tripKg = (tripG / 1000).toFixed(1);
      const whoKeys = Object.keys(totals.by_who)
        .sort((a, b) => (a === 'shared' ? -1 : b === 'shared' ? 1 : a.localeCompare(b)));
      const whoLine = whoKeys.length
        ? whoKeys.map(k => `${escapeHtml(k)} ${totals.by_who[k].toLocaleString()} g`).join('  •  ')
        : '';
      const unkLine = totals.unknown_count
        ? `<span class="gp-warn">⚠ ${totals.unknown_count} item${totals.unknown_count === 1 ? '' : 's'} with unknown weight</span>`
        : '';
      return `
        <div class="gp-header">
          <div class="gp-total"><b>Total: ${tripG.toLocaleString()} g (~${tripKg} kg)</b></div>
          ${whoLine ? `<div class="gp-bywho">${whoLine}</div>` : ''}
          ${unkLine ? `<div>${unkLine}</div>` : ''}
        </div>
      `;
    }

    function renderRow(row, idx) {
      const cat = row.category || '?';
      const eachDisp = row.weight_g_each === null
        ? '?' : row.weight_g_each.toLocaleString();
      const totalDisp = row.weight_g_total === null
        ? '? g' : `${row.weight_g_total.toLocaleString()} g`;
      const isOverride = row.override_weight_g !== null && row.override_weight_g !== undefined;
      const overrideHtml = isOverride
        ? `<input type="number" class="gp-wt-override" min="0" step="1" value="${row.override_weight_g}">
           <a href="#" class="gp-revert">↩ revert</a>`
        : `<span class="gp-wt-each">${eachDisp}</span>
           <a href="#" class="gp-edit-wt">[edit]</a>`;
      const unknownClass = row.unknown_item ? ' gp-unknown' : '';
      const whoOptions = ['shared', ...plan.participants]
        .map(p => `<option value="${escapeHtml(p)}"${row.who === p ? ' selected' : ''}>${escapeHtml(p)}</option>`).join('');
      const itemDisp = row.unknown_item
        ? `<span style="color:#b45309">Unknown: ${escapeHtml(row.item_id || '')}</span>`
        : (row.name ? escapeHtml(row.name) : '');
      const catPill = `<span class="gear-pill" style="background:${pillColor(cat)}">${escapeHtml(cat)}</span>`;
      const warn = row.unknown_weight && !row.unknown_item
        ? `<span class="gp-warn">⚠ unknown weight</span>` : '';
      return `
        <div class="gp-row${unknownClass}" data-idx="${idx}">
          <div class="gp-cell gp-item-cell">
            <input type="text" class="gp-item-input" value="${itemDisp}" placeholder="Type to search gear…" autocomplete="off">
            <div class="gp-item-meta">${catPill} ${warn}</div>
            <ul class="gp-item-suggestions" hidden></ul>
          </div>
          <input type="number" class="gp-qty" min="0" step="1" value="${row.qty || 0}">
          <div class="gp-wt-cell">${overrideHtml}</div>
          <span class="gp-total-wt">${totalDisp}</span>
          <select class="gp-who">${whoOptions}</select>
          <input type="text" class="gp-notes" value="${escapeHtml(row.notes || '')}">
          <button class="gp-remove" title="Remove">×</button>
        </div>
      `;
    }

    function renderTable() {
      if (!totals.items.length) {
        return `<div class="gp-empty">No gear yet. Click + add row to start, or visit Gear DB to populate the catalog first.</div>`;
      }
      const headerRow = `
        <div class="gp-row gp-row-header">
          <span>Item</span><span>Qty</span><span>Wt (each)</span>
          <span>Total</span><span>Who</span><span>Notes</span><span></span>
        </div>
      `;
      return `<div class="gp-table">${headerRow}${totals.items.map((r, i) => renderRow(r, i)).join('')}</div>`;
    }

    function renderLegacyBanner() {
      if (!plan.legacy_body) return '';
      return `
        <div class="gp-legacy-banner">
          This trip has a gear table in <code>gear.md</code> that isn't in the new structured format.
          Saving will replace it — copy anything you want to keep first.
          <button class="gp-view-raw" type="button">View raw</button>
        </div>
      `;
    }

    async function fetchCatalog() {
      const r = await fetch('/api/gear');
      if (r.ok) catalog = await r.json();
    }

    function renderAll() {
      sectionEl.innerHTML = `
        <h2 class="section-title">Shared gear</h2>
        ${renderLegacyBanner()}
        ${renderHeader()}
        ${renderTable()}
        <div class="gp-actions">
          <button class="btn gp-add-row">+ add row</button>
          <button class="btn gp-save">Save</button>
          <span class="gp-status"></span>
        </div>
      `;
      wireBanner();
      wireRows();
      wireFooter();
    }

    function wireBanner() {
      const btn = sectionEl.querySelector('.gp-view-raw');
      if (!btn) return;
      btn.addEventListener('click', () => {
        const w = window.open('', '_blank');
        w.document.body.innerText = plan.legacy_body || '';
      });
    }

    function wireRows() {
      // Row interactivity (autocomplete, qty, who, notes, remove, override-weight)
      // is added in Task 15.
    }

    function wireFooter() {
      const addBtn = sectionEl.querySelector('.gp-add-row');
      if (addBtn) addBtn.addEventListener('click', () => {
        plan.items.push({ item_id: '', qty: 1, who: 'shared', notes: '', override_weight_g: null });
        recomputeTotals();
        renderAll();
      });
      // Save flow added in Task 15.
    }

    fetchCatalog().then(() => {
      recomputeTotals();
      renderAll();
    });
  }

  global.GearPlan = { init };
}(window));
