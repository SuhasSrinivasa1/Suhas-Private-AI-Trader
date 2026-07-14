(() => {
  'use strict';

  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]));
  const base = () => (typeof backendHttp === 'function' ? backendHttp() : 'http://127.0.0.1:8000');
  const wsBase = () => base().replace(/^http/, 'ws');
  const fetchJson = async (path, options = {}, timeout = 15000) => {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeout);
    try {
      const response = await fetch(`${base()}${path}`, {...options, signal: controller.signal});
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || data.message || `HTTP ${response.status}`);
      return data;
    } finally { clearTimeout(timer); }
  };

  let daily = {status:'not_generated', items:[]};
  let status = null;
  let exits = [];
  let analyses = [];
  let health = [];
  let agents = [];
  let socket = null;
  let reconnectTimer = null;
  let lastEvent = null;

  function removeSamples() {
    ['symbol','currentPrice','referencePrice','entryPrice','stopLoss','targetPrice','quantity','portfolioValue','quoteAge','sourceCount'].forEach(id => { if ($(id)) $(id).value = ''; });
    ['newsChecked','technicalChecked','portfolioChecked','liveRequested'].forEach(id => { if ($(id)) $(id).checked = false; });
    document.querySelectorAll('#evaluator button').forEach(button => {
      const action = button.getAttribute('onclick') || '';
      if (action.includes('loadValid') || action.includes('loadRejected')) button.remove();
    });
  }

  function addSection(id, label, html, before='brokers') {
    if ($(id)) return;
    const nav = document.querySelector('.nav');
    const beforeButton = nav?.querySelector(`button[data-section="${before}"]`);
    const button = document.createElement('button');
    button.dataset.section = id;
    button.textContent = label;
    if (beforeButton) nav.insertBefore(button, beforeButton); else nav?.appendChild(button);
    const section = document.createElement('section');
    section.id = id;
    section.className = 'section';
    section.innerHTML = html;
    const main = document.querySelector('main');
    const beforeSection = $(before);
    if (beforeSection) main.insertBefore(section, beforeSection); else main?.appendChild(section);
    button.addEventListener('click', () => {
      document.querySelectorAll('.nav button').forEach(item => item.classList.remove('active'));
      document.querySelectorAll('.section').forEach(item => item.classList.remove('active'));
      button.classList.add('active');
      section.classList.add('active');
    });
  }

  function installUi() {
    addSection('daily', 'Daily Recommendations', `
      <div class="topbar"><div><h1>Automatic Daily Intelligence</h1><p>Automatically generated from Groww 180-day candles, local pattern memory, continuous news memory and deterministic rules. Browser refresh is not required.</p></div><div class="pills"><span>Automatic</span><span>180-day pattern</span><span>Continuous news</span><span>Live confirmation required</span></div></div>
      <div class="grid"><div class="card wide"><div class="section-head"><div><h3>Today's ranked watchlist</h3><p id="p2DailyMeta" class="muted">Waiting for the automatic engine.</p></div><div class="actions"><button class="secondary" onclick="p2ForceDaily()">FORCE REFRESH</button><button class="secondary" onclick="p2AiBrief()">AI DAILY BRIEF</button></div></div><div id="p2DailyStatus" class="warn"><b>Starting…</b></div><div class="table-wrap"><table><thead><tr><th>#</th><th>Symbol</th><th>Status</th><th>Score</th><th>6M pattern</th><th>News</th><th>Rule</th></tr></thead><tbody id="p2DailyRows"></tbody></table></div></div><div class="card narrow"><h3>Decision boundary</h3><div class="warn"><b>No blind premarket BUYs</b><br>A watch candidate becomes actionable only after current market, price, news, risk and anti-chase revalidation.</div><div id="p2ProdStatus" class="warn"><b>Checking Production 2.0…</b></div></div></div>`);

    addSection('intelligence', 'Live Intelligence', `
      <div class="topbar"><div><h1>Always-On Local Intelligence</h1><p>Groww Feed events, automatic Internet news checks, local SQLite memory, semantic retrieval, local Ollama analysis, outcome tracking and bounded agent learning.</p></div><div class="pills"><span>Event driven</span><span>Zero refresh</span><span>SQLite</span><span>Local RAG</span><span>Provider health</span></div></div>
      <div class="grid">
        <div class="card kpi"><label>Groww Feed</label><strong id="p2Feed">STARTING</strong></div><div class="card kpi"><label>Subscriptions</label><strong id="p2Subs">0</strong></div><div class="card kpi"><label>Stored news</label><strong id="p2News">0</strong></div><div class="card kpi"><label>Signals tracked</label><strong id="p2Signals">0</strong></div>
        <div class="card wide"><h3>Automatic local AI analyses</h3><div id="p2Analyses" class="muted">Waiting for a material event.</div></div><div class="card narrow"><h3>Latest engine event</h3><div id="p2Event" class="warn"><b>Waiting for live events…</b></div><div id="p2Memory" class="muted"></div></div>
        <div class="card wide"><h3>Provider health</h3><div class="table-wrap"><table><thead><tr><th>Provider</th><th>Status</th><th>Failures</th><th>Latency</th><th>Message</th></tr></thead><tbody id="p2Health"></tbody></table></div></div><div class="card narrow"><h3>Adaptive agent performance</h3><div id="p2Agents" class="muted">Neutral until enough outcomes are resolved.</div></div>
        <div class="card wide"><h3>SELL / exit intelligence</h3><div class="table-wrap"><table><thead><tr><th>Symbol</th><th>P&amp;L</th><th>Action</th><th>Urgency</th><th>Reason</th><th></th></tr></thead><tbody id="p2Exits"></tbody></table></div><div class="warn"><b>Human confirmation required</b><br>No exit agent or LLM can place an order automatically.</div></div><div class="card narrow"><h3>Cadence</h3><div id="p2Cadence" class="muted"></div></div>
      </div>`);

    const cards = $('brokerCards');
    const info = $('brokerInfo');
    if (cards && info) {
      cards.innerHTML = `<div class="broker"><div><b>Groww Trading API + Live Feed</b><div class="muted">Market feed, historical candles, holdings, positions and human-confirmed execution. Secrets stay in macOS Keychain.</div></div><div class="actions"><button onclick="p2CheckGroww()">TEST READ-ONLY CONNECTION</button><button class="secondary" onclick="p2ReconnectGroww()">RECONNECT FEED</button></div></div>`;
      info.innerHTML = '<b>Groww not checked yet.</b><br>Configure credentials with <code>bash CONFIGURE_GROWW.command</code>, then run the read-only test.';
    }
  }

  function renderDaily() {
    const items = Array.isArray(daily.items) ? daily.items : [];
    if ($('p2DailyMeta')) $('p2DailyMeta').textContent = daily.generated_at ? `Generated ${new Date(daily.generated_at).toLocaleString('en-IN')} · ${daily.universe_size || 0} stocks · ${daily.window_days || 180}-day window` : (daily.message || 'Waiting for automatic generation.');
    if ($('p2DailyStatus')) {
      $('p2DailyStatus').className = daily.status === 'ready' ? 'safe' : 'warn';
      $('p2DailyStatus').innerHTML = daily.status === 'ready' ? '<b>Automatic daily watchlist ready</b><br>The backend continues monitoring market and news events.' : `<b>${esc(String(daily.status || 'not_generated').replaceAll('_',' '))}</b>`;
    }
    if ($('p2DailyRows')) $('p2DailyRows').innerHTML = items.length ? items.map((item, i) => `<tr><td>${i+1}</td><td><b>${esc(item.symbol)}</b></td><td>${esc(item.state || 'WAIT')}</td><td>${Number(item.daily_score || 0).toFixed(1)}</td><td>${Number(item.pattern_score || 0).toFixed(1)} · ${esc(String(item.pattern_label || '').replaceAll('_',' '))}</td><td>${Number(item.news_sentiment || 0).toFixed(2)}</td><td>${esc(item.rule || '')}</td></tr>`).join('') : '<tr><td colspan="7" class="muted">No automatic recommendations loaded yet.</td></tr>';
  }

  function renderIntelligence() {
    const engine = status?.engine || {};
    const feed = engine.feed || {};
    const memory = engine.memory || {};
    if ($('p2Feed')) $('p2Feed').textContent = feed.running ? 'LIVE' : 'OFFLINE';
    if ($('p2Subs')) $('p2Subs').textContent = feed.subscribed_count || 0;
    if ($('p2News')) $('p2News').textContent = memory.news_articles || 0;
    if ($('p2Signals')) $('p2Signals').textContent = memory.signal_snapshots || 0;
    if ($('p2Memory')) $('p2Memory').innerHTML = `Database: ${esc(memory.path || 'local')}<br>Outcomes: ${Number(memory.signal_outcomes || 0)} · LLM analyses: ${Number(memory.llm_analyses || 0)}`;
    if ($('p2Cadence')) $('p2Cadence').innerHTML = `Priority news: ${engine.news_priority_interval_seconds || 15}s<br>Broad rotation: ${engine.news_broad_interval_seconds || 60}s<br>Material move trigger: ${engine.material_price_move_pct || 0.12}%<br>Feed events: push-based<br>LLM: material events only`;
    if ($('p2ProdStatus') && status) {
      $('p2ProdStatus').className = status.broker_configured ? 'safe' : 'warn';
      $('p2ProdStatus').innerHTML = `<b>Production ${esc(status.release)}</b><br>Feed ${feed.running ? 'LIVE' : 'not live yet'} · SQLite ON · Continuous news ON · Local LLM ON · Outcome learning ON · Live execution ${status.live_execution_enabled ? 'ON' : 'OFF'}.`;
    }
    if ($('p2Health')) $('p2Health').innerHTML = health.length ? health.map(item => `<tr><td>${esc(item.provider)}</td><td>${esc(item.status)}</td><td>${Number(item.consecutive_failures || 0)}</td><td>${item.latency_ms == null ? '—' : `${Number(item.latency_ms).toFixed(0)} ms`}</td><td>${esc(item.message || '')}</td></tr>`).join('') : '<tr><td colspan="5" class="muted">No provider status yet.</td></tr>';
    if ($('p2Agents')) $('p2Agents').innerHTML = agents.length ? agents.map(item => `<div class="status-grid"><div><small>${esc(item.agent)}</small><b>${(Number(item.accuracy || 0)*100).toFixed(1)}%</b></div><div><small>Weight</small><b>${Number(item.weight_multiplier || 1).toFixed(2)}×</b></div></div>`).join('') : '<div class="muted">Weights remain neutral until at least 10 resolved outcomes per agent.</div>';
    if ($('p2Analyses')) $('p2Analyses').innerHTML = analyses.length ? analyses.slice(0,10).map(item => `<div class="warn" style="margin-bottom:10px"><b>${esc(item.symbol || 'MARKET')} · ${esc(String(item.event_type || '').replaceAll('_',' '))}</b><br><span style="white-space:pre-wrap">${esc(item.analysis || '')}</span></div>`).join('') : '<div class="muted">Waiting for a material signal or news event.</div>';
    if ($('p2Exits')) $('p2Exits').innerHTML = exits.length ? exits.map(item => {
      const qty = Number(item.quantity || 0);
      const suggested = item.action === 'TRIM_15' ? Math.max(1, Math.round(qty * 0.15)) : Math.max(1, Math.floor(qty));
      const actionable = item.action === 'TRIM_15' || item.action === 'REVIEW_SELL';
      return `<tr><td><b>${esc(item.symbol)}</b></td><td>${Number(item.pnl_pct || 0).toFixed(2)}%</td><td>${esc(item.action)}</td><td>${esc(item.urgency)}</td><td>${esc(item.reason)}</td><td>${actionable ? `<button class="secondary" onclick="p2Sell('${esc(item.symbol)}',${suggested})">${item.action === 'TRIM_15' ? `TRIM ${suggested}` : `SELL ${suggested}`}</button>` : '<span class="muted">Review only</span>'}</td></tr>`;
    }).join('') : '<tr><td colspan="6" class="muted">No current positions requiring an exit review.</td></tr>';
    if ($('p2Event')) $('p2Event').innerHTML = lastEvent ? `<b>${esc(String(lastEvent.type || 'event').replaceAll('_',' '))}</b><br>${esc(lastEvent.summary || lastEvent.symbol || 'Event received.')}<br><small>${lastEvent.ts ? esc(new Date(lastEvent.ts).toLocaleTimeString('en-IN')) : ''}</small>` : '<b>Waiting for live events…</b>';
  }

  async function loadDaily() {
    try { daily = await fetchJson('/api/daily-recommendations'); renderDaily(); } catch (error) { daily = {status:'unavailable', items:[], message:error.message}; renderDaily(); }
  }

  async function loadState() {
    try {
      const results = await Promise.all([
        fetchJson('/api/production/status'), fetchJson('/api/provider-health'), fetchJson('/api/agent-performance'), fetchJson('/api/llm-analyses?limit=20'), fetchJson('/api/exit-signals')
      ]);
      status = results[0]; health = results[1].items || []; agents = results[2].items || []; analyses = results[3].items || []; exits = results[4].items || [];
      renderIntelligence();
    } catch (error) {
      if ($('p2ProdStatus')) $('p2ProdStatus').innerHTML = `<b>Production service unavailable</b><br>${esc(error.message)}`;
    }
  }

  function onEvent(message) {
    if (!message?.type) return;
    if (message.type === 'daily_watchlist' && message.snapshot) { daily = message.snapshot; renderDaily(); }
    if (message.type === 'llm_analysis' && message.item) { analyses.unshift(message.item); analyses = analyses.slice(0,20); }
    if (message.type === 'exit_signals') exits = message.items || [];
    const summary = message.type === 'market_tick' ? `${message.symbol} ₹${Number(message.price || 0).toFixed(2)}`
      : message.type === 'news_event' ? `${message.symbol}: ${Number(message.new_count || 0)} new headline(s)`
      : message.type === 'signal_change' ? `${message.symbol}: ${message.previous || 'NEW'} → ${message.current}`
      : message.type === 'llm_analysis' ? `${message.item?.symbol || 'MARKET'} local AI analysis completed`
      : message.type === 'outcome_update' ? `Outcome tracked at ${message.item?.horizon_minutes || '?'} minutes`
      : message.type;
    lastEvent = {...message, summary};
    renderIntelligence();
  }

  function connectEvents() {
    clearTimeout(reconnectTimer);
    try {
      socket = new WebSocket(`${wsBase()}/ws/live`);
      socket.onmessage = event => { try { onEvent(JSON.parse(event.data)); } catch (_) {} };
      socket.onopen = () => { lastEvent = {type:'websocket_connected', summary:'Zero-refresh event channel connected.', ts:new Date().toISOString()}; renderIntelligence(); };
      socket.onerror = () => socket?.close();
      socket.onclose = () => { reconnectTimer = setTimeout(connectEvents, 2000); };
    } catch (_) { reconnectTimer = setTimeout(connectEvents, 2000); }
  }

  globalThis.p2ForceDaily = async () => { try { daily = await fetchJson('/api/daily-recommendations/refresh', {method:'POST'}, 300000); renderDaily(); } catch (error) { alert(`Daily analysis failed: ${error.message}`); } };
  globalThis.p2CheckGroww = async () => {
    const info = $('brokerInfo');
    if (info) info.innerHTML = '<b>Checking Groww…</b>';
    try {
      const data = await fetchJson('/api/groww/status', {}, 60000);
      if (info) { info.className = data.connected ? 'safe' : 'warn'; info.innerHTML = data.connected ? `<b>Groww connected — read-only verification passed</b><br>Credential source: ${esc(data.credential_source)} · Holdings: ${data.holdings_count || 0} · Positions: ${data.positions_count || 0} · Feed: ${data.feed?.running ? 'LIVE' : 'STARTING'}.` : `<b>Groww not connected</b><br>${esc(data.message || '')}`; }
      await loadState();
    } catch (error) { if (info) info.innerHTML = `<b>Groww check failed</b><br>${esc(error.message)}`; }
  };
  globalThis.p2ReconnectGroww = async () => { try { await fetchJson('/api/groww/reconnect', {method:'POST'}, 60000); } finally { await globalThis.p2CheckGroww(); } };
  globalThis.p2Sell = async (symbol, quantity) => {
    if (!confirm(`Submit a LIVE SELL order to Groww for ${quantity} share(s) of ${symbol}?\n\nThe backend will revalidate market hours, available quantity, current exit signal and fresh price.`)) return;
    try {
      const data = await fetchJson('/api/orders/sell-position', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({symbol, quantity})}, 60000);
      alert(`Groww SELL submitted for ${data.quantity} ${data.symbol} at limit ₹${data.price}. Verify broker order status.`);
    } catch (error) { alert(`SELL blocked or failed: ${error.message}`); }
  };
  globalThis.p2AiBrief = async () => {
    if (!Array.isArray(daily.items) || !daily.items.length) return alert('The automatic daily watchlist has not been generated yet.');
    const modal = $('localAiModal'), title = $('localAiTitle'), body = $('localAiBody');
    if (!modal || !title || !body || typeof localAi === 'undefined') return;
    title.textContent = 'Local AI daily trading brief'; body.innerHTML = '<p>Reviewing locally…</p>'; modal.classList.add('open');
    const system = 'Use only the supplied deterministic watchlist. Never invent prices or news, guarantee profit, create an executable BUY, or bypass a veto. Explain strongest candidates, risks and required live confirmation.';
    try {
      const response = await fetch(`${localAi.baseUrl}/api/chat`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({model:localAi.model, stream:false, keep_alive:'10m', messages:[{role:'system',content:system},{role:'user',content:JSON.stringify(daily)}], options:{temperature:0.1,num_ctx:8192}})});
      const data = await response.json(); if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
      body.innerHTML = `<div class="warn"><b>Advisory local AI</b><br>Only deterministic live revalidation can produce an executable order.</div><div style="white-space:pre-wrap;margin-top:14px">${esc(data.message?.content || 'No briefing returned.')}</div>`;
    } catch (error) { body.innerHTML = `<div class="warn"><b>Local AI brief failed</b><br>${esc(error.message)}</div>`; }
  };

  function init() {
    removeSamples(); installUi(); renderDaily(); renderIntelligence(); loadDaily(); loadState(); globalThis.p2CheckGroww(); connectEvents();
    setInterval(loadState, 5000); setInterval(loadDaily, 60000);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
