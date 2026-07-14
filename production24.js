(() => {
  'use strict';

  const API = 'http://127.0.0.1:8000';
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({
    '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'
  }[c]));
  const json = async path => {
    const response = await fetch(`${API}${path}`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
    return data;
  };

  let strategies = [];
  let duty = null;

  function addStyles() {
    const style = document.createElement('style');
    style.textContent = `
      .p24-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}
      .p24-kpi{background:#132236;border:1px solid #29445f;border-radius:13px;padding:14px}
      .p24-kpi small{display:block;color:#a9bdd0}.p24-kpi b{font-size:1.35rem}
      .p24-gate{padding:12px;border-radius:10px;margin:6px 0}
      .p24-pass{background:#102a25;border:1px solid #2f7664}
      .p24-fail{background:#351a22;border:1px solid #80384b}
      .p24-source{background:#132236;border-left:4px solid #62d6a8;padding:12px;margin:12px 0}
      .p24-strategy{background:#132236;border:1px solid #29445f;border-radius:13px;padding:14px}
      .p24-strategy small{display:block;color:#a9bdd0;line-height:1.4;margin-top:6px}
      .p24-duty{background:#102a25;border:1px solid #2f7664;border-radius:14px;padding:16px;margin-bottom:16px}
      .p24-duty.offhours{background:#132236;border-color:#456789}
      .p24-duty.error{background:#351a22;border-color:#80384b}
      .p24-duty-row{display:flex;justify-content:space-between;gap:14px;align-items:flex-start;flex-wrap:wrap}
      .p24-duty-badge{display:inline-block;border:1px solid #62d6a8;border-radius:999px;padding:6px 10px;font-weight:700}
    `;
    document.head.appendChild(style);
  }

  function install() {
    const nav = document.querySelector('.nav');
    const main = document.querySelector('main');
    if (!nav || !main || document.getElementById('researchLab')) return;

    const button = document.createElement('button');
    button.dataset.section = 'researchLab';
    button.textContent = 'Research & Backtesting';
    const settings = nav.querySelector('[data-section="settings"]');
    settings ? nav.insertBefore(button, settings) : nav.appendChild(button);

    const section = document.createElement('section');
    section.id = 'researchLab';
    section.className = 'section';
    section.innerHTML = `
      <div class="topbar">
        <div>
          <h1>Research & Backtesting Lab</h1>
          <p>Groww-only historical testing, walk-forward validation, Monte Carlo risk, drawdown and always-on market research.</p>
        </div>
        <div class="pills">
          <span>Groww data only</span><span>No mock prices</span><span>24/7 research</span><span>Approval gate</span>
        </div>
      </div>

      <div id="p24Duty" class="p24-duty offhours">
        <div class="p24-duty-row">
          <div>
            <h3 style="margin:0 0 6px">24/7 Local AI Duty</h3>
            <div id="p24DutyText" class="muted">Checking duty engine…</div>
          </div>
          <div class="actions">
            <span id="p24DutyBadge" class="p24-duty-badge">STARTING</span>
            <button class="secondary" id="p24DutyRun">RUN NOW</button>
          </div>
        </div>
      </div>

      <div class="card">
        <div class="form-grid">
          <div><label>NSE symbol</label><input id="p24Symbol" value="RELIANCE"></div>
          <div><label>Strategy</label><select id="p24Strategy"></select></div>
          <div><label>History</label><select id="p24Years"><option>5</option><option>7</option><option>10</option></select></div>
        </div>
        <div class="actions">
          <button id="p24Run">RUN FULL RESEARCH</button>
          <button class="secondary" id="p24Backtest">BACKTEST ONLY</button>
        </div>
        <div class="p24-source">
          <b>Data boundary</b><br>
          Every result must come from Groww historical candles. Missing access returns DATA UNAVAILABLE; no sample result is fabricated.
        </div>
      </div>

      <div id="p24Output" class="card" style="margin-top:16px">
        <div class="muted">Choose a symbol and run research.</div>
      </div>

      <div class="card" style="margin-top:16px">
        <h3>Strategy library</h3>
        <div id="p24Catalog" class="p24-grid"></div>
      </div>
    `;
    main.appendChild(section);

    button.onclick = () => {
      document.querySelectorAll('.nav button').forEach(x => x.classList.remove('active'));
      document.querySelectorAll('.section').forEach(x => x.classList.remove('active'));
      button.classList.add('active');
      section.classList.add('active');
    };

    section.querySelector('#p24Run').onclick = () => runResearch(true);
    section.querySelector('#p24Backtest').onclick = () => runResearch(false);
    section.querySelector('#p24DutyRun').onclick = runDuty;
  }

  function renderCatalog() {
    const select = document.getElementById('p24Strategy');
    const catalog = document.getElementById('p24Catalog');
    if (select) {
      select.innerHTML = strategies.map(x =>
        `<option value="${esc(x.strategy_id)}">${esc(x.name)}</option>`
      ).join('');
    }
    if (catalog) {
      catalog.innerHTML = strategies.map(x =>
        `<div class="p24-strategy">
          <b>${esc(x.name)}</b>
          <small>${esc(x.description)}</small>
          <small><b>Entry:</b> ${esc(x.entry_rules.join(' · '))}</small>
        </div>`
      ).join('');
    }
  }

  function renderDuty() {
    const host = document.getElementById('p24Duty');
    const text = document.getElementById('p24DutyText');
    const badge = document.getElementById('p24DutyBadge');
    if (!host || !text || !badge || !duty) return;

    const mode = duty.mode || 'off_hours_research';
    const status = duty.status || 'starting';
    const best = duty.best_candidate;
    host.className = `p24-duty ${status === 'error' ? 'error' : mode === 'live_market_scan' ? '' : 'offhours'}`;
    badge.textContent = mode === 'live_market_scan' ? 'LIVE MARKET' : 'OFF-HOURS RESEARCH';

    const last = duty.last_run_at
      ? new Date(duty.last_run_at).toLocaleString('en-IN')
      : 'not completed yet';
    const bestText = best
      ? `${esc(best.symbol)} · ${Number(best.confidence || best.rank_score || 0).toFixed(1)}% · WATCH only`
      : 'No ranked candidate yet';

    text.innerHTML = `
      Status: <b>${esc(status.replaceAll('_', ' '))}</b> · Last research: ${esc(last)}<br>
      Best current candidate: <b>${bestText}</b><br>
      ${mode === 'live_market_scan'
        ? 'Groww live scanning is active. Orders remain controlled by the execution and observation gates.'
        : 'The local LLM, news rotation, historical patterns and Groww last-known data remain active. Every candidate requires fresh live revalidation after NSE opens.'}
    `;
  }

  async function loadDuty() {
    try {
      duty = await json('/api/duty/status');
      renderDuty();
    } catch (error) {
      duty = {status:'error', mode:'off_hours_research', last_error:error.message};
      renderDuty();
    }
  }

  async function runDuty() {
    const button = document.getElementById('p24DutyRun');
    if (button) {
      button.disabled = true;
      button.textContent = 'WORKING…';
    }
    try {
      const response = await fetch(`${API}/api/duty/run`, {method:'POST'});
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
      duty = data;
      renderDuty();
    } catch (error) {
      alert(`Always-on research failed: ${error.message}`);
    } finally {
      if (button) {
        button.disabled = false;
        button.textContent = 'RUN NOW';
      }
    }
  }

  function metrics(m) {
    return `<div class="p24-grid">
      <div class="p24-kpi"><small>Total trades</small><b>${m.total_trades}</b></div>
      <div class="p24-kpi"><small>Win rate</small><b>${Number(m.win_rate_pct).toFixed(1)}%</b></div>
      <div class="p24-kpi"><small>Profit factor</small><b>${Number(m.profit_factor).toFixed(2)}</b></div>
      <div class="p24-kpi"><small>CAGR</small><b>${Number(m.cagr_pct).toFixed(1)}%</b></div>
      <div class="p24-kpi"><small>Sharpe</small><b>${Number(m.sharpe).toFixed(2)}</b></div>
      <div class="p24-kpi"><small>Max drawdown</small><b>${Number(m.max_drawdown_pct).toFixed(1)}%</b></div>
    </div>`;
  }

  async function runResearch(full) {
    const symbol = document.getElementById('p24Symbol').value.trim().toUpperCase();
    const strategy = document.getElementById('p24Strategy').value;
    const years = document.getElementById('p24Years').value;
    const output = document.getElementById('p24Output');
    output.innerHTML = '<div class="warn"><b>Loading real Groww candles…</b></div>';

    try {
      const data = await json(
        full
          ? `/api/research/full-report/${encodeURIComponent(symbol)}/${strategy}?years=${years}`
          : `/api/research/backtest/${encodeURIComponent(symbol)}/${strategy}?years=${years}`
      );

      if (!full) {
        output.innerHTML = `
          <h3>${esc(symbol)} · ${esc(data.strategy.name)}</h3>
          <div class="p24-source">Source: ${esc(data.source_metadata.provider)} · ${data.candle_count} valid candles · costs included</div>
          ${metrics(data.metrics)}
        `;
        return;
      }

      const gates = data.approval.gates;
      output.innerHTML = `
        <h3>${esc(symbol)} · Full research report</h3>
        <div class="p24-source">Groww Trading API only · no mock market data</div>
        ${metrics(data.backtest.metrics)}
        <h4>Walk-forward</h4>
        <p>${data.walk_forward.summary.profitable_test_windows}/${data.walk_forward.summary.windows}
          profitable out-of-sample windows ·
          ${Number(data.walk_forward.summary.out_of_sample_consistency_pct).toFixed(1)}%</p>
        <h4>Monte Carlo</h4>
        <div class="p24-grid">
          <div class="p24-kpi"><small>Probability of profit</small><b>${Number(data.monte_carlo.probability_of_profit_pct).toFixed(1)}%</b></div>
          <div class="p24-kpi"><small>Probability ≥10% loss</small><b>${Number(data.monte_carlo.probability_of_10pct_loss_pct).toFixed(1)}%</b></div>
          <div class="p24-kpi"><small>Probability ₹1 lakh</small><b>${Number(data.monte_carlo.probability_reach_1_lakh_pct).toFixed(4)}%</b></div>
        </div>
        <h4>Approval gate</h4>
        ${Object.entries(gates).map(([key,value]) =>
          `<div class="p24-gate ${value ? 'p24-pass' : 'p24-fail'}">
            <b>${value ? 'PASS' : 'FAIL'}</b> · ${esc(key.replaceAll('_',' '))}
          </div>`
        ).join('')}
        <div class="warn">
          <b>${data.approval.approved_for_paper_observation ? 'Eligible for paper observation' : 'Rejected for paper observation'}</b><br>
          ${esc(data.approval.reason)}
        </div>
      `;
    } catch (error) {
      output.innerHTML = `
        <div class="warn">
          <b>DATA UNAVAILABLE</b><br>
          ${esc(error.message)}<br>
          No mock or synthetic result was substituted.
        </div>
      `;
    }
  }

  async function init() {
    addStyles();
    install();
    try {
      strategies = (await json('/api/research/strategies')).items || [];
      renderCatalog();
    } catch (_) {}
    await loadDuty();
    setInterval(loadDuty, 30000);
  }

  const previous = document.createElement('script');
  previous.src = 'production23.js';
  previous.onload = init;
  previous.onerror = init;
  document.head.appendChild(previous);
})();
