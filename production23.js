(() => {
  'use strict';

  const API = 'http://127.0.0.1:8000';
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]));
  let payload = {items: [], summary: null};
  let timer = null;

  async function json(path, options = {}) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch(`${API}${path}`, {...options, signal: controller.signal});
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || data.message || `HTTP ${response.status}`);
      return data;
    } finally { clearTimeout(timeout); }
  }

  function addStyles() {
    const style = document.createElement('style');
    style.textContent = `
      .p23-kpis{display:grid;grid-template-columns:repeat(5,minmax(120px,1fr));gap:12px;margin-bottom:16px}
      .p23-kpi{background:#132236;border:1px solid #29445f;border-radius:14px;padding:15px}.p23-kpi small{display:block;color:#9fb2c5;margin-bottom:8px}.p23-kpi b{font-size:1.55rem}
      .p23-results-grid{display:grid;grid-template-columns:minmax(0,1.4fr) minmax(300px,.6fr);gap:16px}.p23-donut-wrap{display:flex;align-items:center;gap:24px;flex-wrap:wrap}
      .p23-donut{width:190px;height:190px;border-radius:50%;display:grid;place-items:center;position:relative}.p23-donut:after{content:'';width:120px;height:120px;border-radius:50%;background:#0e1726;position:absolute}.p23-donut-center{position:relative;z-index:1;text-align:center}.p23-donut-center b{display:block;font-size:1.8rem}.p23-legend div{margin:8px 0}.p23-dot{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:8px}
      .p23-bars{display:flex;align-items:flex-end;gap:8px;height:170px;padding:15px 5px 0}.p23-day{flex:1;min-width:22px;text-align:center}.p23-stack{height:130px;display:flex;flex-direction:column-reverse;border-radius:7px;overflow:hidden;background:#25384c}.p23-good{background:#62d6a8}.p23-bad{background:#ff6b7d}.p23-open{background:#7891aa}.p23-day small{display:block;margin-top:6px;font-size:10px;color:#9fb2c5}
      .p23-learning{padding:14px;border-radius:12px;background:#112b29;border:1px solid #2d776c;margin-bottom:12px}.p23-warmup{padding:14px;border-radius:12px;background:#2b2411;border:1px solid #7b672d;margin-bottom:12px}
      .p23-status{font-weight:800}.p23-correct{color:#62d6a8}.p23-wrong{color:#ff6b7d}.p23-pending{color:#9fb2c5}.p23-table td{vertical-align:top}.p23-price{white-space:nowrap}
      @media(max-width:1000px){.p23-kpis{grid-template-columns:repeat(2,minmax(120px,1fr))}.p23-results-grid{grid-template-columns:1fr}}@media(max-width:600px){.p23-kpis{grid-template-columns:1fr}.p23-donut{width:160px;height:160px}}
    `;
    document.head.appendChild(style);
  }

  function installSection() {
    if (document.getElementById('callsResults')) return;
    const nav = document.querySelector('.nav');
    const main = document.querySelector('main');
    if (!nav || !main) return;
    const button = document.createElement('button');
    button.dataset.section = 'callsResults';
    button.textContent = 'Calls & Results';
    const journalButton = nav.querySelector('[data-section="journal"]');
    if (journalButton) nav.insertBefore(button, journalButton); else nav.appendChild(button);

    const section = document.createElement('section');
    section.id = 'callsResults';
    section.className = 'section';
    section.innerHTML = `
      <div class="topbar"><div><h1>Calls & Results</h1><p>Paper predictions made by the model, their proposed buy and sell prices, and whether the target was reached before the stop. These records are not actual user trades.</p></div><div class="pills"><span>Paper calls</span><span>7-day observation</span><span>Automatic scoring</span><span>Precision calibration</span></div></div>
      <div id="p23Warmup" class="p23-warmup"><b>Loading observation phase…</b></div>
      <div class="p23-kpis"><div class="p23-kpi"><small>Total calls</small><b id="p23Total">0</b></div><div class="p23-kpi"><small>Correct</small><b id="p23Correct" class="p23-correct">0</b></div><div class="p23-kpi"><small>Wrong</small><b id="p23Wrong" class="p23-wrong">0</b></div><div class="p23-kpi"><small>Still open</small><b id="p23Open">0</b></div><div class="p23-kpi"><small>Resolved accuracy</small><b id="p23Accuracy">0.0%</b></div></div>
      <div class="p23-results-grid">
        <div class="card"><div class="section-head"><div><h3>Correct vs wrong calls</h3><p class="muted">Open calls are not counted in accuracy until their target, stop or evaluation deadline resolves them.</p></div><button id="p23Refresh" class="secondary">REFRESH RESULTS</button></div><div class="p23-donut-wrap"><div id="p23Donut" class="p23-donut"><div class="p23-donut-center"><b id="p23DonutAccuracy">0%</b><small>accuracy</small></div></div><div class="p23-legend"><div><span class="p23-dot p23-good"></span>Correct: <b id="p23LegendCorrect">0</b></div><div><span class="p23-dot p23-bad"></span>Wrong: <b id="p23LegendWrong">0</b></div><div><span class="p23-dot p23-open"></span>Open: <b id="p23LegendOpen">0</b></div></div></div><h4>Daily call outcomes</h4><div id="p23Bars" class="p23-bars"></div></div>
        <div class="card"><h3>Automatic learning status</h3><div id="p23Learning" class="p23-learning"></div><div class="warn"><b>Critical statistical safeguard</b><br>The system targets very high precision by becoming more selective. A 99% target is not a guarantee, and unresolved calls cannot be counted as correct. Risk rules cannot be weakened to improve the displayed percentage.</div></div>
      </div>
      <div class="card" style="margin-top:16px"><div class="section-head"><div><h3>Prediction ledger</h3><p class="muted">Each call records a predicted buy price, predicted sell target, stop loss, confidence and automatic result.</p></div><div><select id="p23ModeFilter"><option value="">All modes</option><option value="intraday">Intraday</option><option value="delivery">Delivery</option></select> <select id="p23StatusFilter"><option value="">All results</option><option value="OPEN">Open</option><option value="CORRECT">Correct</option><option value="WRONG">Wrong</option></select></div></div><div class="table-wrap"><table class="p23-table"><thead><tr><th>Time</th><th>Symbol</th><th>Mode</th><th>Prediction</th><th>Buy</th><th>Sell target</th><th>Stop</th><th>Resolved price</th><th>Result</th><th>Return</th><th>Confidence</th></tr></thead><tbody id="p23Rows"></tbody></table></div></div>`;
    main.appendChild(section);
    button.addEventListener('click', () => {
      document.querySelectorAll('.nav button').forEach(x => x.classList.remove('active'));
      document.querySelectorAll('.section').forEach(x => x.classList.remove('active'));
      button.classList.add('active'); section.classList.add('active');
    });
    section.querySelector('#p23Refresh').addEventListener('click', refreshResults);
    section.querySelector('#p23ModeFilter').addEventListener('change', loadResults);
    section.querySelector('#p23StatusFilter').addEventListener('change', loadResults);
  }

  function number(value, digits = 2) { return Number(value || 0).toFixed(digits); }
  function price(value) { return value == null ? '—' : `₹${Number(value).toLocaleString('en-IN',{minimumFractionDigits:2,maximumFractionDigits:2})}`; }

  function renderSummary() {
    const s = payload.summary || {};
    const correct = Number(s.correct_calls || 0), wrong = Number(s.wrong_calls || 0), open = Number(s.open_calls || 0), total = Number(s.total_calls || 0);
    const accuracy = Number(s.accuracy_pct || 0);
    document.getElementById('p23Total').textContent = total;
    document.getElementById('p23Correct').textContent = correct;
    document.getElementById('p23Wrong').textContent = wrong;
    document.getElementById('p23Open').textContent = open;
    document.getElementById('p23Accuracy').textContent = `${number(accuracy,1)}%`;
    document.getElementById('p23DonutAccuracy').textContent = `${number(accuracy,1)}%`;
    document.getElementById('p23LegendCorrect').textContent = correct;
    document.getElementById('p23LegendWrong').textContent = wrong;
    document.getElementById('p23LegendOpen').textContent = open;
    const denominator = Math.max(1,total);
    const c = correct / denominator * 100, w = wrong / denominator * 100;
    document.getElementById('p23Donut').style.background = `conic-gradient(#62d6a8 0 ${c}%,#ff6b7d ${c}% ${c+w}%,#7891aa ${c+w}% 100%)`;

    const observation = s.observation || {};
    const warm = document.getElementById('p23Warmup');
    if (observation.complete) {
      warm.className = 'safe';
      warm.innerHTML = '<b>Seven-day paper-observation phase complete.</b><br>Calls continue to be logged. Any future live order still requires all normal confirmations and risk checks.';
    } else {
      warm.className = 'p23-warmup';
      warm.innerHTML = `<b>Paper-observation phase active — ${number(observation.remaining_days,2)} days remaining.</b><br>The model is receiving live data and logging predictions, but these are not trades and live BUY submission is blocked during this phase.`;
    }

    const learning = s.learning || {};
    document.getElementById('p23Learning').innerHTML = `<b>State: ${esc(String(learning.state || 'collecting').replace(/_/g,' '))}</b><br>Precision target: ${number(learning.target_precision_pct,2)}% <b>(not guaranteed)</b><br>Resolved sample: ${Number(learning.resolved_calls || 0)} / ${Number(learning.minimum_samples || 50)} minimum<br>Observed accuracy: ${number(learning.observed_accuracy_pct,2)}%<br>Current recommended BUY confidence: ≥ ${number(learning.recommended_min_confidence,1)}<br>95% lower confidence bound: ${number(Number(learning.wilson_lower_bound || 0)*100,2)}%`;

    const days = Array.isArray(s.daily) ? s.daily : [];
    const max = Math.max(1,...days.map(x => Number(x.total || 0)));
    document.getElementById('p23Bars').innerHTML = days.length ? days.map(day => {
      const good = Number(day.correct_count || 0), bad = Number(day.wrong_count || 0), pending = Math.max(0,Number(day.total || 0)-good-bad);
      const scale = 130 / max;
      return `<div class="p23-day" title="${esc(day.day)} · ${good} correct · ${bad} wrong · ${pending} open"><div class="p23-stack"><div class="p23-good" style="height:${Math.max(0,good*scale)}px"></div><div class="p23-bad" style="height:${Math.max(0,bad*scale)}px"></div><div class="p23-open" style="height:${Math.max(0,pending*scale)}px"></div></div><small>${esc(String(day.day || '').slice(5))}</small></div>`;
    }).join('') : '<div class="muted">Daily outcome bars will appear after the first model calls.</div>';
  }

  function renderRows() {
    const rows = document.getElementById('p23Rows');
    const items = Array.isArray(payload.items) ? payload.items : [];
    rows.innerHTML = items.length ? items.map(item => {
      const status = String(item.status || 'OPEN');
      const cls = status === 'CORRECT' ? 'p23-correct' : status === 'WRONG' ? 'p23-wrong' : 'p23-pending';
      return `<tr><td>${esc(new Date(item.predicted_at).toLocaleString('en-IN'))}</td><td><b>${esc(item.symbol)}</b></td><td>${esc(item.trading_mode)}</td><td>BUY → SELL TARGET</td><td class="p23-price">${price(item.predicted_buy_price)}</td><td class="p23-price">${price(item.predicted_sell_price)}</td><td class="p23-price">${price(item.stop_loss)}</td><td class="p23-price">${price(item.resolved_price)}</td><td><span class="p23-status ${cls}">${esc(status)}</span><br><small>${esc(String(item.result_reason || '').replace(/_/g,' '))}</small></td><td>${item.return_pct == null ? '—' : `${number(item.return_pct,2)}%`}</td><td>${number(item.confidence,1)}</td></tr>`;
    }).join('') : '<tr><td colspan="11" class="muted">No paper calls recorded yet. The first qualified BUY prediction will appear here automatically.</td></tr>';
  }

  async function loadResults() {
    try {
      const mode = document.getElementById('p23ModeFilter')?.value || '';
      const status = document.getElementById('p23StatusFilter')?.value || '';
      const query = new URLSearchParams({limit:'500'});
      if (mode) query.set('mode',mode);
      if (status) query.set('status',status);
      payload = await json(`/api/calls-results?${query.toString()}`);
      renderSummary(); renderRows();
    } catch (error) {
      const rows = document.getElementById('p23Rows');
      if (rows) rows.innerHTML = `<tr><td colspan="11" class="muted">Calls & Results unavailable: ${esc(error.message)}</td></tr>`;
    }
  }

  async function refreshResults() {
    try { await json('/api/calls-results/refresh',{method:'POST'}); } catch (_) {}
    await loadResults();
  }

  function init() {
    addStyles(); installSection(); loadResults();
    timer = setInterval(loadResults, 15000);
    window.addEventListener('beforeunload', () => clearInterval(timer), {once:true});
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, {once:true}); else init();
})();
