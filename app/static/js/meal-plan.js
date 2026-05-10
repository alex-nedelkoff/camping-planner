/* Trip-page meal planner. Mounted by trip.js when a section has kind=meal-plan. */
(function (global) {
  'use strict';

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  const ACTIVITY_DEFAULTS = {
    'backcountry': 4000, 'bikepacking': 4500,
    'boat-camping': 3500, 'car-camping': 2500,
  };

  function init(sectionEl, slug, payload) {
    let plan = (payload && payload.plan) || { calorie_target: { activity_level: 'backcountry', kcal_per_person_per_day: 4000 }, days: [], participants: [], legacy_body: '' };
    let totals = (payload && payload.totals) || { trip_kcal: 0, target_kcal: 0, delta_kcal: 0, days: [] };
    let catalog = { foods: [], categories: [] };

    function recomputeTotals() {
      const byId = Object.fromEntries(catalog.foods.map(f => [f.id, f]));
      const days = plan.days.map(d => {
        const meals = (d.meals || []).map(m => {
          const items = (m.items || []).map(it => {
            const f = byId[it.food_id];
            const kcal = f ? (parseInt(it.servings, 10) || 0) * (f.kcal_per_serving || 0) : null;
            return { ...it, kcal, unknown_food: !f };
          });
          const mk = items.filter(i => i.kcal !== null).reduce((a, b) => a + b.kcal, 0);
          return { ...m, items, kcal: mk };
        });
        const dk = meals.reduce((a, b) => a + b.kcal, 0);
        return { ...d, meals, kcal: dk };
      });
      const trip = days.reduce((a, b) => a + b.kcal, 0);
      const tgt = (plan.days.length || 0) * (plan.participants.length || 0) * (plan.calorie_target.kcal_per_person_per_day || 0);
      totals = { days, trip_kcal: trip, target_kcal: tgt, delta_kcal: trip - tgt };
    }

    function renderHeader() {
      const tgt = totals.target_kcal || 1;
      const pct = Math.round((totals.trip_kcal / tgt) * 100);
      const pctClamped = Math.max(0, Math.min(150, pct));
      const inRange = pct >= 95 && pct <= 110;
      return `
        <div class="mp-header">
          <div class="mp-target-row">
            <label>Activity level
              <select class="mp-activity">
                ${['backcountry','bikepacking','boat-camping','car-camping'].map(k =>
                  `<option value="${k}"${plan.calorie_target.activity_level === k ? ' selected' : ''}>${k}</option>`).join('')}
              </select>
            </label>
            <label>kcal / person / day
              <input type="number" class="mp-kcd" min="0" step="50" value="${plan.calorie_target.kcal_per_person_per_day}">
            </label>
            <span class="mp-summary">
              ${plan.days.length} days × ${plan.participants.length} people ×
              ${plan.calorie_target.kcal_per_person_per_day} = <b>${totals.target_kcal.toLocaleString()} kcal target</b>
            </span>
          </div>
          <div class="mp-progress" data-status="${inRange ? 'ok' : 'warn'}">
            <div class="mp-bar" style="width:${pctClamped}%"></div>
            <span class="mp-progress-label">
              Planned: ${totals.trip_kcal.toLocaleString()} kcal — ${pct}%
              ${totals.delta_kcal >= 0 ? `(surplus ${totals.delta_kcal.toLocaleString()})` : `(short ${Math.abs(totals.delta_kcal).toLocaleString()})`}
            </span>
          </div>
        </div>
      `;
    }

    function renderDayCard(day) {
      // Day cards collapsed by default (`<details>`).
      return `
        <details class="mp-day" data-date="${escapeHtml(day.date)}">
          <summary>
            <span class="mp-day-label">${escapeHtml(day.label || '')} (${escapeHtml(day.date)})</span>
            <span class="mp-day-total">${day.kcal.toLocaleString()} kcal</span>
          </summary>
          <div class="mp-meals" data-date="${escapeHtml(day.date)}">
            ${(day.meals || []).map((m, i) => renderMeal(day.date, m, i)).join('')}
            <button class="mp-add-meal" data-date="${escapeHtml(day.date)}">+ add meal</button>
          </div>
        </details>
      `;
    }

    function renderMeal(date, meal, mealIdx) {
      return `
        <div class="mp-meal" data-date="${escapeHtml(date)}" data-meal-idx="${mealIdx}">
          <h4>${escapeHtml(meal.meal[0].toUpperCase() + meal.meal.slice(1))}
            <button class="mp-remove-meal" title="Remove this meal">×</button>
          </h4>
          <div class="mp-items">
            ${meal.items.map((it, i) => renderItemRow(date, mealIdx, i, it)).join('')}
          </div>
          <button class="mp-add-item" type="button">+ add item</button>
        </div>
      `;
    }

    function renderItemRow(date, mealIdx, itemIdx, item) {
      const food = catalog.foods.find(f => f.id === item.food_id);
      const display = food ? food.name : (item.food_id || '');
      const kcalDisplay = item.kcal === null || item.kcal === undefined ? '?' : item.kcal;
      const unknownClass = item.unknown_food ? ' mp-unknown' : '';
      const whoOptions = ['shared', ...plan.participants]
        .map(p => `<option value="${escapeHtml(p)}"${item.who === p ? ' selected' : ''}>${escapeHtml(p)}</option>`).join('');
      return `
        <div class="mp-item${unknownClass}" data-date="${escapeHtml(date)}" data-meal-idx="${mealIdx}" data-item-idx="${itemIdx}">
          <div class="mp-food-cell">
            <input type="text" class="mp-food-input" value="${escapeHtml(display)}" placeholder="Type to search foods…" autocomplete="off">
            <ul class="mp-food-suggestions" hidden></ul>
          </div>
          <input type="number" class="mp-servings" min="0" step="1" value="${item.servings || 0}">
          <span class="mp-kcal">${kcalDisplay} kcal</span>
          <select class="mp-who">${whoOptions}</select>
          <button class="mp-remove-item" title="Remove">×</button>
        </div>
      `;
    }

    function renderLegacyBanner() {
      if (!plan.legacy_body) return '';
      return `
        <div class="mp-legacy-banner">
          This trip has notes in <code>food.md</code> that aren't in the new structured format.
          Saving will replace them — copy anything you want to keep first.
          <button class="mp-view-raw" type="button">View raw</button>
        </div>
      `;
    }

    async function fetchCatalog() {
      const r = await fetch('/api/foods');
      if (r.ok) catalog = await r.json();
    }

    function renderAll() {
      sectionEl.innerHTML = `
        <h2 class="section-title">Food</h2>
        ${renderLegacyBanner()}
        ${renderHeader()}
        <div class="mp-days">
          ${totals.days.map(renderDayCard).join('')}
        </div>
        <div class="mp-actions">
          <button class="btn mp-save">Save</button>
          <span class="mp-status"></span>
        </div>
      `;
      wireHeader();
      wireLegacyBanner();
      wireDayChrome();
      wireSave();
    }

    function wireHeader() {
      const sel = sectionEl.querySelector('.mp-activity');
      const inp = sectionEl.querySelector('.mp-kcd');
      sel.addEventListener('change', (e) => {
        plan.calorie_target.activity_level = e.target.value;
        plan.calorie_target.kcal_per_person_per_day = ACTIVITY_DEFAULTS[e.target.value] || 4000;
        recomputeTotals();
        renderAll();
      });
      inp.addEventListener('change', (e) => {
        plan.calorie_target.kcal_per_person_per_day = parseInt(e.target.value, 10) || 0;
        recomputeTotals();
        renderAll();
      });
    }

    function wireLegacyBanner() {
      const btn = sectionEl.querySelector('.mp-view-raw');
      if (!btn) return;
      btn.addEventListener('click', () => {
        const w = window.open('', '_blank');
        w.document.body.innerText = plan.legacy_body || '';
      });
    }

    function wireDayChrome() {
      // + add meal
      sectionEl.querySelectorAll('.mp-add-meal').forEach(btn => {
        btn.addEventListener('click', () => {
          const date = btn.dataset.date;
          const day = plan.days.find(d => d.date === date);
          if (!day) return;
          const choice = prompt('Meal type? (breakfast / lunch / dinner / snack)', 'dinner');
          if (!choice) return;
          day.meals = day.meals || [];
          day.meals.push({ meal: choice, items: [] });
          recomputeTotals();
          renderAll();
        });
      });

      // - remove meal
      sectionEl.querySelectorAll('.mp-remove-meal').forEach(btn => {
        btn.addEventListener('click', () => {
          const mealEl = btn.closest('.mp-meal');
          const date = mealEl.dataset.date;
          const idx = parseInt(mealEl.dataset.mealIdx, 10);
          const day = plan.days.find(d => d.date === date);
          day.meals.splice(idx, 1);
          recomputeTotals();
          renderAll();
        });
      });

      // + add item to meal
      sectionEl.querySelectorAll('.mp-add-item').forEach(btn => {
        btn.addEventListener('click', () => {
          const mealEl = btn.closest('.mp-meal');
          const date = mealEl.dataset.date;
          const idx = parseInt(mealEl.dataset.mealIdx, 10);
          const day = plan.days.find(d => d.date === date);
          day.meals[idx].items = day.meals[idx].items || [];
          day.meals[idx].items.push({ food_id: '', servings: 1, who: 'shared', note: '' });
          recomputeTotals();
          renderAll();
        });
      });

      // remove item
      sectionEl.querySelectorAll('.mp-remove-item').forEach(btn => {
        btn.addEventListener('click', () => {
          const itemEl = btn.closest('.mp-item');
          const date = itemEl.dataset.date;
          const mealIdx = parseInt(itemEl.dataset.mealIdx, 10);
          const itemIdx = parseInt(itemEl.dataset.itemIdx, 10);
          const day = plan.days.find(d => d.date === date);
          day.meals[mealIdx].items.splice(itemIdx, 1);
          recomputeTotals();
          renderAll();
        });
      });

      // servings input
      sectionEl.querySelectorAll('.mp-servings').forEach(inp => {
        inp.addEventListener('change', (e) => {
          const itemEl = inp.closest('.mp-item');
          const date = itemEl.dataset.date;
          const mealIdx = parseInt(itemEl.dataset.mealIdx, 10);
          const itemIdx = parseInt(itemEl.dataset.itemIdx, 10);
          const day = plan.days.find(d => d.date === date);
          day.meals[mealIdx].items[itemIdx].servings = parseInt(e.target.value, 10) || 0;
          recomputeTotals();
          renderAll();
        });
      });

      // who select
      sectionEl.querySelectorAll('.mp-who').forEach(sel => {
        sel.addEventListener('change', (e) => {
          const itemEl = sel.closest('.mp-item');
          const date = itemEl.dataset.date;
          const mealIdx = parseInt(itemEl.dataset.mealIdx, 10);
          const itemIdx = parseInt(itemEl.dataset.itemIdx, 10);
          const day = plan.days.find(d => d.date === date);
          day.meals[mealIdx].items[itemIdx].who = e.target.value;
        });
      });

      // food autocomplete
      sectionEl.querySelectorAll('.mp-food-input').forEach(inp => wireAutocomplete(inp));
    }

    function wireAutocomplete(inp) {
      const itemEl = inp.closest('.mp-item');
      const date = itemEl.dataset.date;
      const mealIdx = parseInt(itemEl.dataset.mealIdx, 10);
      const itemIdx = parseInt(itemEl.dataset.itemIdx, 10);
      const sugs = itemEl.querySelector('.mp-food-suggestions');

      function close() { sugs.hidden = true; sugs.innerHTML = ''; }

      inp.addEventListener('input', () => {
        const q = inp.value.toLowerCase().trim();
        const matches = catalog.foods
          .filter(f => f.name.toLowerCase().includes(q))
          .slice(0, 8);
        const exact = catalog.foods.some(f => f.name.toLowerCase() === q);
        sugs.innerHTML = matches.map(f =>
          `<li data-id="${escapeHtml(f.id)}">${escapeHtml(f.name)} <span class="mp-cat">${escapeHtml(f.category)}</span></li>`
        ).join('');
        if (q && !exact) {
          sugs.innerHTML += `<li class="mp-create" data-create="${escapeHtml(inp.value)}">+ Create "${escapeHtml(inp.value)}" as new food</li>`;
        }
        sugs.hidden = sugs.innerHTML === '';
        sugs.querySelectorAll('li[data-id]').forEach(li => {
          li.addEventListener('click', () => {
            const day = plan.days.find(d => d.date === date);
            day.meals[mealIdx].items[itemIdx].food_id = li.dataset.id;
            close();
            recomputeTotals();
            renderAll();
          });
        });
        sugs.querySelectorAll('li.mp-create').forEach(li => {
          li.addEventListener('click', () => openCreateFoodModal(li.dataset.create, date, mealIdx, itemIdx));
        });
      });
      inp.addEventListener('blur', () => setTimeout(close, 150));
    }

    function openCreateFoodModal(name, date, mealIdx, itemIdx) {
      const overlay = document.createElement('div');
      overlay.className = 'mp-modal-overlay';
      const catOpts = catalog.categories
        .map(c => `<option value="${c}">${c}</option>`).join('');
      overlay.innerHTML = `
        <div class="mp-modal">
          <h3>Create new food</h3>
          <div class="mp-modal-error" hidden></div>
          <label>Name <input type="text" id="mpf-name" value="${escapeHtml(name)}"></label>
          <label>Category <select id="mpf-category">${catOpts}</select></label>
          <label>kcal per serving <input type="number" id="mpf-kcal" min="0" step="1" value="0"></label>
          <label>Serving size <input type="text" id="mpf-serving" placeholder="1 pouch (113 g)"></label>
          <label>URL (optional) <input type="url" id="mpf-url" placeholder="https://..."></label>
          <div class="mp-modal-actions">
            <button class="btn" id="mpf-create">Create + select</button>
            <button class="btn secondary" id="mpf-cancel">Cancel</button>
          </div>
        </div>
      `;
      document.body.appendChild(overlay);
      const close = () => overlay.remove();
      overlay.querySelector('#mpf-cancel').addEventListener('click', close);
      overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
      overlay.querySelector('#mpf-create').addEventListener('click', async () => {
        const payload = {
          name: overlay.querySelector('#mpf-name').value.trim(),
          category: overlay.querySelector('#mpf-category').value,
          kcal_per_serving: parseInt(overlay.querySelector('#mpf-kcal').value, 10) || 0,
          serving_size: overlay.querySelector('#mpf-serving').value.trim(),
          url: overlay.querySelector('#mpf-url').value.trim() || null,
        };
        const r = await fetch('/api/foods', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        if (!r.ok) {
          const j = await r.json().catch(() => ({}));
          const err = overlay.querySelector('.mp-modal-error');
          err.textContent = (j.detail && j.detail.error) || `HTTP ${r.status}`;
          err.hidden = false;
          return;
        }
        const { id: newId } = await r.json();
        // Reload catalog, set the item.food_id, recompute, rerender.
        const cr = await fetch('/api/foods');
        catalog = await cr.json();
        const day = plan.days.find(d => d.date === date);
        day.meals[mealIdx].items[itemIdx].food_id = newId;
        close();
        recomputeTotals();
        renderAll();
      });
    }

    function wireSave() {
      const btn = sectionEl.querySelector('.mp-save');
      const status = sectionEl.querySelector('.mp-status');
      btn.addEventListener('click', async () => {
        status.textContent = 'Saving…';
        // Strip computed kcal/unknown_food fields before sending
        const cleanDays = plan.days.map(d => ({
          date: d.date, label: d.label || '',
          meals: (d.meals || []).map(m => ({
            meal: m.meal,
            items: (m.items || []).map(it => ({
              food_id: it.food_id || '',
              servings: parseInt(it.servings, 10) || 0,
              who: it.who || '',
              note: it.note || '',
            })),
          })),
        }));
        const payload = {
          calorie_target: plan.calorie_target,
          days: cleanDays,
        };
        const r = await fetch(`/api/trip/${encodeURIComponent(slug)}/meals`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        if (!r.ok) {
          const j = await r.json().catch(() => ({}));
          status.textContent = 'Error: ' + ((j.detail && j.detail.error) || `HTTP ${r.status}`);
          return;
        }
        status.textContent = 'Saved.';
        // Clear legacy banner state — body has been regenerated.
        plan.legacy_body = '';
        renderAll();
        setTimeout(() => { status.textContent = ''; }, 2000);
      });
    }

    fetchCatalog().then(() => {
      recomputeTotals();
      renderAll();
    });
  }

  global.MealPlan = { init };
}(window));
