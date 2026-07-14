(() => {
  'use strict';

  const API = 'http://127.0.0.1:8000';
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]));
  let status = null;
  let agents = [];

  async function json(path, options = {}) {
    const response = await fetch(`${API}${path}`, options);
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || data.message || `HTTP ${response.status}`);
    return data;
  }

  function installStyles() {
    const style = document.createElement('style');
    style.textContent = `
      .p22-mode-gate{position:fixed;inset:0;z-index:10000;background:rgba(5,10,18,.92);display:none;align-items:center;justify-content:center;padding:24px;backdrop-filter:blur(10px)}
      .p22-mode-gate.open{display:flex}.p22-mode-panel{max-width:920px;width:100%;background:#0e1726;border:1px solid #31506f;border-radius:20px;padding:26px;box-shadow:0 25px 80px rgba(0,0,0,.5)}
      .p22-mode-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px;margin-top:20px}.p22-mode-card{background:#132236;border:1px solid #31506f;border-radius:16px;padding:20px;text-align:left;color:inherit;cursor:pointer}
      .p22-mode-card:hover,.p22-mode-card.selected{border-color:#62d6a8;transform:translateY(-1px)}.p22-mode-card h3{margin:0 0 8px}.p22-mode-card small{display:block;line-height:1.55;color:#a9bdd0}
      .p22-active-mode{position:fixed;right:18px;bottom:18px;z-index:5000;background:#14263b;border:1px solid #62d6a8;border-radius:999px;padding:10px 15px;color:#dfffee;font-weight:700;cursor:pointer}
      .p22-agent-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:12px}.p22-agent{background:#132236;border:1px solid #29445f;border-radius:13px;padding:14px}.p22-agent small{display:block;color:#a9bdd0;margin-top:6px;line-height:1.45}
      .p22-agent-weight{margin-top:9px;color:#62d6a8;font-weight:700}.p22-macd{margin:14px 0;padding:13px;border-radius:12px;background:#102a25;border:1px solid #2f7664}
      @media(max-width:700px){.p22-mode-grid{grid-template-columns:1fr}.p22-mode-panel{padding:18px}}
    `;
    document.head.appendChild(style);
  }

  function installGate() {
    if (document.getElementById('p22ModeGate')) return;
    const gate = document.createElement('div');
    gate.id = 'p22ModeGate'; gate.className = 'p22-mode-gate';
    gate.innerHTML = `<div class="p22-mode-panel"><h2>Choose your trading mode</h2><p class="muted">The selected mode changes candle timeframes, specialist-agent weights, holding period and Groww product. MACD 12/26/9 is mandatory in both modes.</p><div class="p22-mode-grid"><button class="p22-mode-card" data-mode="intraday"><h3>Intraday</h3><small>Groww MIS · same-day trade · 5-minute and 15-minute MACD alignment · higher order-flow and liquidity weight.</small></button><button class="p22-mode-card" data-mode="delivery"><h3>Delivery</h3><small>Groww CNC · multi-day holding · daily MACD and six-month structure · higher trend and news weight.</small></button></div><div class="p22-macd"><b>Mandatory indicators</b><br>MACD 12/26/9 · RSI 14 · EMA 20/50 · ATR 14 · volume confirmation.</div></div>`;
    document.body.appendChild(gate);
    gate.querySelectorAll('[data-mode]').forEach(button => button.addEventListener('click', () => setMode(button.dataset.mode)));

    const pill = document.createElement('button'); pill.id = 'p22ActiveMode'; pill.className = 'p22-active-mode'; pill.textContent = 'SELECT MODE';
    pill.addEventListener('click', () => gate.classList.add('open')); document.body.appendChild(pill);
  }

  function installAgentLab() {
    if (document.getElementById('p22AgentLab')) return;
    const nav = document.querySelector('.nav');
    const main = document.querySelector('main');
    if (!nav || !main) return;
    const button = document.createElement('button'); button.dataset.section = 'p22AgentLab'; button.textContent = 'Agent Lab'; nav.appendChild(button);
    const section = document.createElement('section'); section.id = 'p22AgentLab'; section.className = 'section';
    section.innerHTML = `<div class="topbar"><div><h1>Mode-Specific Agent Lab</h1><p>Independent specialist agents score each setup. The risk-veto agent can block a BUY regardless of total score.</p></div><div class="pills"><span>MACD 12/26/9</span><span>12 specialists</span><span>MIS / CNC aware</span></div></div><div class="card"><div class="section-head"><div><h3 id="p22AgentTitle">Specialist ensemble</h3><p id="p22AgentDescription" class="muted"></p></div><button class="secondary" id="p22ChangeMode">CHANGE MODE</button></div><div id="p22MacdPolicy" class="p22-macd"></div><div id="p22Agents" class="p22-agent-grid"></div></div>`;
    main.appendChild(section);
    button.addEventListener('click', () => {
      document.querySelectorAll('.nav button').forEach(x => x.classList.remove('active'));
      document.querySelectorAll('.section').forEach(x => x.classList.remove('active'));
      button.classList.add('active'); section.classList.add('active');
    });
    section.querySelector('#p22ChangeMode').addEventListener('click', () => document.getElementById('p22ModeGate').classList.add('open'));
  }

  function render() {
    const mode = status?.mode || '';
    const profile = status?.profile || {};
    const pill = document.getElementById('p22ActiveMode');
    if (pill) pill.textContent = mode ? `${profile.label || mode.toUpperCase()} · ${profile.broker_product || ''}` : 'SELECT MODE';
    document.querySelectorAll('.p22-mode-card').forEach(x => x.classList.toggle('selected', x.dataset.mode === mode));
    const title = document.getElementById('p22AgentTitle'); if (title) title.textContent = `${profile.label || 'Mode'} specialist ensemble`;
    const description = document.getElementById('p22AgentDescription'); if (description) description.textContent = profile.description || '';
    const macd = document.getElementById('p22MacdPolicy'); if (macd) macd.innerHTML = `<b>MACD mandatory</b><br>Fast EMA 12 · Slow EMA 26 · Signal EMA 9 · Timeframes: ${esc((profile.primary_timeframes || []).join(' + '))}`;
    const host = document.getElementById('p22Agents');
    if (host) host.innerHTML = agents.map(agent => `<div class="p22-agent"><b>${esc(agent.name)}</b><small>${esc(agent.purpose)}</small><div class="p22-agent-weight">Mode weight ${(Number(agent.weight || 0) * 100).toFixed(0)}%</div></div>`).join('');
  }

  async function loadMode() {
    try {
      status = await json('/api/trading-mode');
      const saved = localStorage.getItem('privateAiTraderMode');
      if (!saved) document.getElementById('p22ModeGate').classList.add('open');
      else if (saved !== status.mode) status = await json('/api/trading-mode', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mode:saved})});
      agents = (await json('/api/specialist-agents')).items || [];
      render();
    } catch (error) {
      document.getElementById('p22ModeGate').classList.add('open');
      console.error('Mode initialization failed', error);
    }
  }

  async function setMode(mode) {
    try {
      status = await json('/api/trading-mode', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mode})});
      localStorage.setItem('privateAiTraderMode', mode);
      agents = (await json('/api/specialist-agents')).items || [];
      document.getElementById('p22ModeGate').classList.remove('open'); render();
      if (typeof globalThis.scanNow === 'function') globalThis.scanNow();
    } catch (error) { alert(`Mode change failed: ${error.message}`); }
  }

  function overrideBuy() {
    globalThis.buyRecommendation = async recommendationId => {
      const mode = status?.mode || localStorage.getItem('privateAiTraderMode');
      if (!mode) return document.getElementById('p22ModeGate').classList.add('open');
      const product = mode === 'delivery' ? 'CNC delivery' : 'MIS intraday';
      if (!confirm(`Submit a LIVE ${mode.toUpperCase()} BUY using Groww ${product}?\n\nThe backend will run fresh price, MACD, specialist-agent, news, risk and anti-chase validation.`)) return;
      try {
        const data = await json('/api/orders/buy-recommendation', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({recommendation_id:recommendationId})});
        const order = data.order || {};
        alert(`Groww ${String(data.trading_mode || mode).toUpperCase()} order submitted using ${data.broker_product || product}.\nOrder ID: ${order.groww_order_id || 'See broker response'}\nStatus: ${order.order_status || 'Submitted'}`);
      } catch (error) { alert(`BUY blocked or failed: ${error.message}`); }
    };
  }

  function init22() { installStyles(); installGate(); installAgentLab(); overrideBuy(); loadMode(); }
  const legacy = document.createElement('script'); legacy.src = 'production21.js'; legacy.onload = init22; legacy.onerror = init22; document.head.appendChild(legacy);
})();
