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
            ${(day.meals || []).map(m => renderMeal(day.date, m)).join('')}
            <button class="mp-add-meal" data-date="${escapeHtml(day.date)}">+ add meal</button>
          </div>
        </details>
      `;
    }

    function renderMeal(date, meal) {
      // Item rows added in Task 13.
      return `
        <div class="mp-meal" data-meal="${escapeHtml(meal.meal)}">
          <h4>${escapeHtml(meal.meal[0].toUpperCase() + meal.meal.slice(1))}</h4>
          <div class="mp-items"><!-- item rows in Task 13 --></div>
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
      // Item-row + add-meal wiring in Task 13.
    }

    fetchCatalog().then(() => {
      recomputeTotals();
      renderAll();
    });
  }

  global.MealPlan = { init };
}(window));
