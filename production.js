(() => {
  'use strict';

  const byId = id => document.getElementById(id);
  const escapeValue = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[char]));
  const apiBase = () => (typeof backendHttp === 'function' ? backendHttp() : 'http://127.0.0.1:8000');
  const request = async (url, options = {}, timeoutMs = 120000) => {
    if (typeof fetchWithTimeout === 'function') return fetchWithTimeout(url, options, timeoutMs);
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try { return await fetch(url, {...options, signal: controller.signal}); }
    finally { clearTimeout(timer); }
  };

  let dailySnapshot = {status:'not_generated',items:[]};

  function removeSampleUi() {
    const evaluatorFields = ['symbol','currentPrice','referencePrice','entryPrice','stopLoss','targetPrice','quantity','portfolioValue','quoteAge','sourceCount'];
    evaluatorFields.forEach(id => { const element = byId(id); if (element) element.value = ''; });
    ['newsChecked','technicalChecked','portfolioChecked','liveRequested'].forEach(id => { const element = byId(id); if (element) element.checked = false; });
    document.querySelectorAll('#evaluator button').forEach(button => {
      const action = button.getAttribute('onclick') || '';
      if (action.includes('loadValid') || action.includes('loadRejected')) button.remove();
    });
    const decision = byId('decisionBox');
    if (decision) {
      decision.className = 'decision wait';
      const strong = decision.querySelector('strong');
      if (strong) strong.textContent = 'READY';
    }
    if (byId('decisionText')) byId('decisionText').textContent = 'Enter real current values from your verified data source.';
    ['rr','riskPct','chasePct','positionRisk'].forEach(id => { if (byId(id)) byId(id).textContent = '—'; });
    if (byId('reasons')) byId('reasons').innerHTML = '<li>No evaluation yet.</li>';
  }

  function installDailySection() {
    if (byId('daily')) return;
    const nav = document.querySelector('.nav');
    const settingsButton = nav?.querySelector('button[data-section="settings"]');
    const button = document.createElement('button');
    button.dataset.section = 'daily';
    button.textContent = 'Daily Recommendations';
    if (settingsButton) nav.insertBefore(button, settingsButton); else nav?.appendChild(button);

    const main = document.querySelector('main');
    const brokerSection = byId('brokers');
    const section = document.createElement('section');
    section.id = 'daily';
    section.className = 'section';
    section.innerHTML = `
      <div class="topbar">
        <div><h1>Daily AI Trading Brief</h1><p>Production watchlist built from Groww's rolling 180-day daily candles, the six-month pattern agent, free news-risk checks, and deterministic trading rules. Premarket results require live revalidation before any BUY.</p></div>
        <div class="pills"><span>180-day pattern</span><span>Free news-risk check</span><span>Local AI brief</span><span>Live revalidation required</span></div>
      </div>
      <div class="grid">
        <div class="card wide">
          <div class="section-head"><div><h3>Today's ranked watchlist</h3><p id="dailyMeta" class="muted">No daily analysis generated yet.</p></div><div class="actions"><button id="dailyRefreshButton" onclick="refreshDailyRecommendations()">REFRESH 180-DAY ANALYSIS</button><button class="secondary" onclick="reviewDailyBriefWithLocalAI()">AI DAILY BRIEF</button></div></div>
          <div id="dailyStatus" class="warn"><b>Waiting for production engine.</b></div>
          <div class="table-wrap"><table><thead><tr><th>#</th><th>Symbol</th><th>Status</th><th>Daily score</th><th>6M pattern</th><th>20D</th><th>60D</th><th>120D</th><th>Volatility</th><th>News</th></tr></thead><tbody id="dailyRows"><tr><td colspan="10" class="muted">No production recommendations loaded.</td></tr></tbody></table></div>
        </div>
        <div class="card narrow">
          <h3>Production decision boundary</h3>
          <div class="warn"><b>No blind premarket BUYs</b><br>A daily WATCH candidate is not an executable order. The live scanner must confirm current price, market regime, liquidity, order flow, portfolio exposure, news risk, anti-chase distance, and the six-month pattern before BUY can appear.</div>
          <div id="productionStatus" class="warn"><b>Checking production services…</b></div>
        </div>
      </div>`;
    if (brokerSection) main.insertBefore(section, brokerSection); else main.appendChild(section);

    button.addEventListener('click', () => {
      document.querySelectorAll('.nav button').forEach(item => item.classList.remove('active'));
      document.querySelectorAll('.section').forEach(item => item.classList.remove('active'));
      button.classList.add('active');
      section.classList.add('active');
    });
  }

  function installGrowwProductionPanel() {
    const cards = byId('brokerCards');
    const info = byId('brokerInfo');
    if (!cards || !info) return;
    cards.innerHTML = `
      <div class="broker">
        <div><b>Groww Trading API</b><div class="muted">Production connection · credentials stored in macOS Keychain · never in this browser</div></div>
        <div class="actions"><button onclick="checkGrowwProductionStatus()">TEST READ-ONLY CONNECTION</button><button class="secondary" onclick="reconnectGrowwProduction()">RECONNECT</button></div>
      </div>`;
    info.innerHTML = '<b>Groww not checked yet.</b><br>Run <code>bash scripts/mac/configure_groww.sh</code> on the Mac, approve the API key in Groww when required, then test the read-only connection here.';
  }

  function renderDaily() {
    const rows = byId('dailyRows');
    const meta = byId('dailyMeta');
    const status = byId('dailyStatus');
    if (!rows || !meta || !status) return;

    const items = Array.isArray(dailySnapshot.items) ? dailySnapshot.items : [];
    meta.textContent = dailySnapshot.generated_at
      ? `Generated ${new Date(dailySnapshot.generated_at).toLocaleString('en-IN')} · ${dailySnapshot.universe_size || 0} configured liquid NSE stocks · ${dailySnapshot.window_days || 180}-day window`
      : (dailySnapshot.message || 'No daily analysis generated yet.');

    if (dailySnapshot.status !== 'ready') {
      status.className = 'warn';
      status.innerHTML = `<b>${escapeValue(String(dailySnapshot.status || 'not_generated').replaceAll('_',' '))}</b><br>${escapeValue(dailySnapshot.message || 'Connect Groww and refresh the daily analysis.')}`;
    } else {
      status.className = 'safe';
      status.innerHTML = '<b>Daily production watchlist ready</b><br>Every candidate is a watch item only until live market revalidation passes.';
    }

    rows.innerHTML = items.length ? items.map((item, index) => {
      const state = escapeValue(item.state || 'WAIT');
      const pattern = `${Number(item.six_month_pattern_score || 0).toFixed(1)} · ${escapeValue(String(item.six_month_pattern_label || '').replaceAll('_',' '))}`;
      const news = item.news_status === 'ok'
        ? `${Number(item.news_sentiment || 0).toFixed(2)} sentiment`
        : escapeValue(String(item.news_status || 'unknown').replaceAll('_',' '));
      return `<tr><td>${index + 1}</td><td><b>${escapeValue(item.symbol)}</b></td><td>${state}</td><td>${Number(item.daily_score || 0).toFixed(1)}</td><td>${pattern}</td><td>${Number(item.return_20d_pct || 0).toFixed(1)}%</td><td>${Number(item.return_60d_pct || 0).toFixed(1)}%</td><td>${Number(item.return_120d_pct || 0).toFixed(1)}%</td><td>${Number(item.annualized_volatility_pct || 0).toFixed(1)}%</td><td>${news}</td></tr>`;
    }).join('') : '<tr><td colspan="10" class="muted">No daily candidates are available yet.</td></tr>';
  }

  async function loadDailyRecommendations() {
    try {
      const response = await request(`${apiBase()}/api/daily-recommendations`, {}, 10000);
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Daily recommendations unavailable.');
      dailySnapshot = data;
      renderDaily();
    } catch (error) {
      dailySnapshot = {status:'unavailable',items:[],message:error.message};
      renderDaily();
    }
  }

  globalThis.refreshDailyRecommendations = async function refreshDailyRecommendations() {
    const button = byId('dailyRefreshButton');
    if (button) { button.disabled = true; button.textContent = 'ANALYZING 180 DAYS…'; }
    const status = byId('dailyStatus');
    if (status) status.innerHTML = '<b>Running production analysis…</b><br>Fetching and scoring six months of daily candles across the configured liquid universe.';
    try {
      const response = await request(`${apiBase()}/api/daily-recommendations/refresh`, {method:'POST'}, 300000);
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Daily analysis failed.');
      dailySnapshot = data;
      renderDaily();
    } catch (error) {
      alert(`Daily analysis failed: ${error.name === 'AbortError' ? 'Request timed out.' : error.message}`);
      await loadDailyRecommendations();
    } finally {
      if (button) { button.disabled = false; button.textContent = 'REFRESH 180-DAY ANALYSIS'; }
    }
  };

  globalThis.reviewDailyBriefWithLocalAI = async function reviewDailyBriefWithLocalAI() {
    const items = Array.isArray(dailySnapshot.items) ? dailySnapshot.items : [];
    if (!items.length) return alert('Generate the daily production watchlist first.');
    const modal = byId('localAiModal');
    const title = byId('localAiTitle');
    const body = byId('localAiBody');
    if (!modal || !title || !body) return;
    title.textContent = 'Local AI daily trading brief';
    body.innerHTML = '<div class="muted">The local LLM is reviewing only the deterministic daily watchlist. It cannot create a BUY, bypass a veto, or place an order.</div><p>Reviewing locally…</p>';
    modal.classList.add('open');
    const snapshot = {
      generated_for: dailySnapshot.generated_for,
      method: dailySnapshot.method,
      items: items.map(item => ({
        symbol:item.symbol,state:item.state,daily_score:item.daily_score,six_month_pattern_score:item.six_month_pattern_score,
        six_month_pattern_label:item.six_month_pattern_label,return_20d_pct:item.return_20d_pct,return_60d_pct:item.return_60d_pct,
        return_120d_pct:item.return_120d_pct,annualized_volatility_pct:item.annualized_volatility_pct,max_drawdown_pct:item.max_drawdown_pct,
        news_status:item.news_status,news_sentiment:item.news_sentiment,risk_flags:item.risk_flags,
      })),
    };
    const system = 'You are the private local AI portfolio and trading briefing agent. Use only the supplied deterministic watchlist. Do not invent prices, news, or guarantees. Do not convert a WATCH into a BUY. Explain the top candidates, key six-month patterns, major risks, and what live confirmation is still required. Keep the output practical and concise.';
    try {
      const response = await request(`${localAi.baseUrl}/api/chat`, {
        method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({model:localAi.model,stream:false,keep_alive:'10m',messages:[{role:'system',content:system},{role:'user',content:JSON.stringify(snapshot,null,2)}],options:{temperature:0.15,num_ctx:8192}}),
      }, 180000);
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
      body.innerHTML = `<div class="warn"><b>Advisory local AI</b><br>Only live deterministic revalidation can produce an executable BUY.</div><div style="white-space:pre-wrap;margin-top:14px">${escapeValue(data.message?.content || 'No briefing returned.')}</div>`;
    } catch (error) {
      body.innerHTML = `<div class="warn"><b>Local AI daily brief failed</b><br>${escapeValue(error.name === 'AbortError' ? 'The local model timed out.' : error.message)}</div>`;
    }
  };

  globalThis.checkGrowwProductionStatus = async function checkGrowwProductionStatus() {
    const info = byId('brokerInfo');
    if (info) info.innerHTML = '<b>Checking Groww…</b><br>Running a read-only holdings and positions verification.';
    try {
      const response = await request(`${apiBase()}/api/groww/status`, {}, 30000);
      const data = await response.json();
      if (data.connected) {
        info.className = 'safe';
        info.innerHTML = `<b>Groww connected — read-only verification passed</b><br>Credential source: ${escapeValue(data.credential_source)} · Holdings: ${Number(data.holdings_count || 0)} · Positions: ${Number(data.positions_count || 0)}. Live execution remains ${liveState?.live_execution_enabled ? 'ON' : 'OFF'}.`;
      } else {
        info.className = 'warn';
        info.innerHTML = `<b>Groww not connected</b><br>${escapeValue(data.message || 'Check Keychain credentials and daily API approval.')}`;
      }
      return data;
    } catch (error) {
      if (info) { info.className = 'warn'; info.innerHTML = `<b>Groww status check failed</b><br>${escapeValue(error.message)}`; }
      return null;
    }
  };

  globalThis.reconnectGrowwProduction = async function reconnectGrowwProduction() {
    const info = byId('brokerInfo');
    if (info) info.innerHTML = '<b>Reconnecting Groww…</b>';
    try {
      await request(`${apiBase()}/api/groww/reconnect`, {method:'POST'}, 30000);
    } finally {
      await globalThis.checkGrowwProductionStatus();
    }
  };

  async function loadProductionStatus() {
    const element = byId('productionStatus');
    try {
      const response = await request(`${apiBase()}/api/production/status`, {}, 10000);
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Production status unavailable.');
      element.className = 'safe';
      element.innerHTML = `<b>Production release ${escapeValue(data.release)}</b><br>No sample data · Local-only web service · Six-month pattern agent ON · Daily engine ON · Free news-risk check ON · Ollama local AI · Groww ${data.broker_configured ? 'configured' : 'not configured'} · Live execution ${data.live_execution_enabled ? 'ON' : 'OFF'}.`;
    } catch (error) {
      if (element) element.innerHTML = `<b>Production service unavailable</b><br>${escapeValue(error.message)}`;
    }
  }

  function initializeProductionUi() {
    removeSampleUi();
    installDailySection();
    installGrowwProductionPanel();
    loadProductionStatus();
    loadDailyRecommendations();
    globalThis.checkGrowwProductionStatus();
    setInterval(loadDailyRecommendations, 300000);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initializeProductionUi);
  else initializeProductionUi();
})();
