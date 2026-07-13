const RUNTIME = window.PAI_RUNTIME || {};
const DEFAULT_POLICY = {
  enabled: true,
  allowLiveExecution: false,
  maxRiskPerTradePct: 1,
  minRewardRiskRatio: 2,
  maxChasePct: 1.5,
  maxPriceAgeSeconds: 120,
  minConfirmationSources: 2,
};
const DEFAULT_LOCAL_AI = {
  enabled: true,
  baseUrl: RUNTIME.ollamaBaseUrl || 'http://127.0.0.1:11434',
  model: RUNTIME.ollamaModel || 'gpt-oss:20b',
};

function readLocalJson(key, fallback) {
  try {
    const value = JSON.parse(localStorage.getItem(key) || 'null');
    return value ?? fallback;
  } catch (_) {
    return fallback;
  }
}

function readSessionJson(key, fallback) {
  try {
    const value = JSON.parse(sessionStorage.getItem(key) || 'null');
    return value ?? fallback;
  } catch (_) {
    return fallback;
  }
}

let policy = {...DEFAULT_POLICY, ...readLocalJson('pai_policy', {})};
let localAi = {...DEFAULT_LOCAL_AI, ...readLocalJson('pai_local_ai', {})};
let portfolio = readLocalJson('pai_portfolio', []);
let evaluations = Number(localStorage.getItem('pai_evaluations') || '0');
let liveState = {
  connected: false,
  lastEvent: null,
  prices: {},
  news: [],
  holdings: [],
  positions: [],
  orders: [],
  recommendations: {},
  opportunities: [],
  live_execution_enabled: false,
  market_regime: {score: 50, label: 'neutral'},
  scan_at: null,
  scanner_universe_size: 0,
};
let liveSocket = null;
let reconnectTimer = null;
const skippedSignals = new Set(readSessionJson('pai_skipped_signals', []));

const $ = id => document.getElementById(id);
const num = id => Number($(id)?.value || 0);
const checked = id => Boolean($(id)?.checked);
const money = value => new Intl.NumberFormat('en-IN', {
  style: 'currency', currency: 'INR', maximumFractionDigits: 2,
}).format(Number(value) || 0);
const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;',
}[char]));

function backendHttp() {
  if (RUNTIME.backendBaseUrl) return String(RUNTIME.backendBaseUrl).replace(/\/$/, '');
  return `${location.protocol === 'https:' ? 'https' : 'http'}://${location.hostname || '127.0.0.1'}:8000`;
}

function backendWs() {
  const base = backendHttp();
  return `${base.replace(/^http:/, 'ws:').replace(/^https:/, 'wss:')}/ws/live`;
}

async function fetchWithTimeout(url, options = {}, timeoutMs = 5000) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, {...options, signal: controller.signal});
  } finally {
    clearTimeout(timeoutId);
  }
}

function saveSkipped() {
  sessionStorage.setItem('pai_skipped_signals', JSON.stringify([...skippedSignals]));
}

function isExpired(recommendation) {
  if (!recommendation?.generated_at) return false;
  const ageSeconds = (Date.now() - new Date(recommendation.generated_at).getTime()) / 1000;
  return ageSeconds > Number(recommendation.valid_for_seconds || 20);
}

function signalAge(recommendation) {
  if (!recommendation?.generated_at) return '—';
  const ageSeconds = Math.max(0, Math.floor((Date.now() - new Date(recommendation.generated_at).getTime()) / 1000));
  return `${ageSeconds}s`;
}

function latestPrice(symbol) {
  const key = Object.keys(liveState.prices).find(item => item.endsWith(`:${symbol}`) || item === symbol);
  const event = key ? liveState.prices[key] : null;
  return event?.ltp ?? event?.price ?? event?.last_price ?? null;
}

function playAlert() {
  try {
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextClass) return;
    const context = new AudioContextClass();
    const oscillator = context.createOscillator();
    const gain = context.createGain();
    oscillator.connect(gain);
    gain.connect(context.destination);
    oscillator.frequency.value = 880;
    gain.gain.setValueAtTime(0.08, context.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, context.currentTime + 0.35);
    oscillator.start();
    oscillator.stop(context.currentTime + 0.35);
  } catch (_) {
    // Audio alerts are optional and may be blocked until the user interacts with Safari.
  }
}

function renderDashboard() {
  const source = liveState.holdings.length ? liveState.holdings : portfolio;
  const value = source.reduce((sum, position) => {
    const symbol = position.trading_symbol || position.symbol || position.tradingsymbol || '';
    const quantity = Number(position.quantity ?? position.qty ?? 0);
    const average = Number(position.average_price ?? position.avg ?? position.averagePrice ?? 0);
    const livePrice = latestPrice(symbol);
    return sum + quantity * (Number(livePrice) || average);
  }, 0);

  if ($('kpiPortfolio')) $('kpiPortfolio').textContent = money(value);
  if ($('kpiPositions')) $('kpiPositions').textContent = String(liveState.positions.length || source.length);

  const execution = $('liveExecutionStatus');
  if (execution) {
    execution.textContent = liveState.live_execution_enabled ? 'ON' : 'OFF';
    execution.className = liveState.live_execution_enabled ? '' : 'off';
  }

  const regime = $('marketRegime');
  if (regime) regime.textContent = `${String(liveState.market_regime?.label || 'neutral').toUpperCase()} · ${Number(liveState.market_regime?.score || 50).toFixed(0)}`;
  const universe = $('scannerUniverse');
  if (universe) universe.textContent = String(liveState.scanner_universe_size || 0);

  const table = $('dashboardPositions');
  if (table) {
    table.innerHTML = source.length ? source.slice(-8).reverse().map(position => {
      const symbol = position.trading_symbol || position.symbol || position.tradingsymbol || '';
      const market = position.exchange || position.market || 'NSE';
      const quantity = Number(position.quantity ?? position.qty ?? 0);
      const average = Number(position.average_price ?? position.avg ?? position.averagePrice ?? 0);
      const livePrice = latestPrice(symbol);
      return `<tr><td>${esc(symbol)}</td><td>${esc(market)}</td><td>${quantity}</td><td>${average || '—'}</td><td>${money(quantity * (Number(livePrice) || average))}</td></tr>`;
    }).join('') : '<tr><td colspan="5" class="muted">No positions saved.</td></tr>';
  }

  renderLiveStatus();
  renderRecommendations();
  renderOpportunityCount();
}

function renderPortfolio() {
  const rows = $('portfolioRows');
  if (rows) {
    rows.innerHTML = portfolio.length ? portfolio.map((position, index) => `
      <tr>
        <td>${esc(position.symbol)}</td><td>${esc(position.market)}</td><td>${position.qty}</td>
        <td>${position.avg}</td><td>${money(position.qty * (latestPrice(position.symbol) || position.avg))}</td>
        <td><button class="secondary" onclick="removePosition(${index})">Remove</button></td>
      </tr>`).join('') : '<tr><td colspan="6" class="muted">No positions saved.</td></tr>';
  }
  renderDashboard();
}

function renderLiveStatus() {
  const status = $('liveStatus');
  if (!status) return;
  status.className = liveState.connected ? 'safe' : 'warn';
  const detail = liveState.scan_at
    ? `Last scan: ${new Date(liveState.scan_at).toLocaleTimeString('en-IN')}`
    : liveState.lastEvent
      ? `Last event: ${new Date(liveState.lastEvent).toLocaleTimeString('en-IN')}`
      : 'Waiting for backend events.';
  status.innerHTML = `<b>${liveState.connected ? 'Agentic scanner connected' : 'Scanner disconnected'}</b><br>${esc(detail)}`;
}

function renderNews() {
  const box = $('liveNews');
  if (!box) return;
  box.innerHTML = liveState.news.length
    ? liveState.news.slice(0, 12).map(item => `<div class="broker"><div><b>${esc(item.title || 'Headline')}</b><div class="muted">${esc(item.source || '')}${item.published ? ` · ${esc(item.published)}` : ''}</div></div></div>`).join('')
    : '<div class="muted">News agent is neutral until a configured provider is connected; it does not invent sentiment.</div>';
}

function renderOpportunityCount() {
  const element = $('opportunityCount');
  if (!element) return;
  const buys = Object.values(liveState.recommendations || {}).filter(item => item.state === 'BUY' && !isExpired(item) && !skippedSignals.has(item.recommendation_id));
  element.textContent = String(buys.length);
}

function sortedRecommendations() {
  return Object.values(liveState.recommendations || {})
    .filter(item => !isExpired(item))
    .sort((a, b) => ((b.state === 'BUY') - (a.state === 'BUY'))
      || ((b.state === 'WATCHING') - (a.state === 'WATCHING'))
      || Number(b.rank_score || b.confidence || 0) - Number(a.rank_score || a.confidence || 0));
}

function renderRecommendations() {
  const board = $('recommendationBoard');
  if (!board) return;
  const items = sortedRecommendations();
  if (!items.length) {
    board.innerHTML = '<div class="muted">Scanner is running. No current opportunity has passed the ranking threshold.</div>';
    return;
  }

  board.innerHTML = items.map((item, index) => {
    const isBuy = item.state === 'BUY';
    const skipped = skippedSignals.has(item.recommendation_id);
    const canExecute = isBuy && !skipped && liveState.live_execution_enabled;
    const reasons = (item.reasons || []).slice(0, 3).map(esc).join(' · ');
    const veto = (item.risk_vetoes || []).slice(0, 2).map(esc).join(' · ');
    return `<div class="opportunity-card ${isBuy ? 'buy-opportunity' : item.state === 'WATCHING' ? 'watch-opportunity' : ''}">
      <div class="rank-badge">#${index + 1}</div>
      <div class="opportunity-main">
        <div class="opportunity-title"><b>${esc(item.symbol)}</b><span class="state-pill ${String(item.state || 'WAIT').toLowerCase()}">${esc(item.state || item.action)}</span><span class="confidence">${Number(item.confidence || 0).toFixed(0)}% confidence</span></div>
        <div class="price-grid"><span><small>Buy</small><b>${money(item.entry_price)}</b></span><span><small>Target</small><b>${money(item.target_price)}</b></span><span><small>Stop</small><b>${money(item.stop_loss)}</b></span><span><small>Qty</small><b>${Number(item.quantity || 0)}</b></span><span><small>R:R</small><b>${Number(item.reward_risk_ratio || 0).toFixed(1)}</b></span><span><small>Age</small><b>${signalAge(item)}</b></span></div>
        <div class="agent-row">${Object.entries(item.agent_scores || {}).map(([key, value]) => `<span>${esc(key)} ${Number(value).toFixed(0)}</span>`).join('')}</div>
        <div class="muted">${reasons || veto || 'No additional explanation available.'}</div>
        ${veto ? `<div class="veto-text">Risk veto: ${veto}</div>` : ''}
      </div>
      <div class="opportunity-actions">
        <button class="secondary" onclick="reviewWithLocalAI('${esc(item.recommendation_id)}')">AI REVIEW</button>
        ${isBuy && !skipped
          ? `<button ${canExecute ? '' : 'disabled'} onclick="buyRecommendation('${esc(item.recommendation_id)}')">${canExecute ? 'BUY NOW' : 'LIVE OFF'}</button><button class="secondary" onclick="skipRecommendation('${esc(item.recommendation_id)}')">SKIP</button>`
          : skipped
            ? '<button class="secondary" disabled>SKIPPED</button>'
            : `<button class="secondary" disabled>${esc(item.state || 'WAIT')}</button>`}
      </div>
    </div>`;
  }).join('');
}

function skipRecommendation(recommendationId) {
  skippedSignals.add(recommendationId);
  saveSkipped();
  closeAlertModal();
  renderRecommendations();
  renderOpportunityCount();
}

function showBuyAlert(items) {
  const fresh = (items || []).filter(item => item.state === 'BUY' && !isExpired(item) && !skippedSignals.has(item.recommendation_id));
  if (!fresh.length) return;
  playAlert();
  const modal = $('buyAlertModal');
  const body = $('buyAlertBody');
  const title = $('buyAlertTitle');
  if (!modal || !body || !title) return;
  title.textContent = fresh.length === 1 ? `BUY opportunity: ${fresh[0].symbol}` : `${fresh.length} BUY opportunities detected`;
  body.innerHTML = fresh.map((item, index) => `<div class="alert-opportunity"><div><b>#${index + 1} ${esc(item.symbol)} · ${Number(item.confidence || 0).toFixed(0)}%</b><div class="muted">Buy ${money(item.entry_price)} · Target ${money(item.target_price)} · Stop ${money(item.stop_loss)} · Qty ${Number(item.quantity || 0)}</div></div><div class="actions"><button class="secondary" onclick="reviewWithLocalAI('${esc(item.recommendation_id)}')">AI REVIEW</button><button ${liveState.live_execution_enabled ? '' : 'disabled'} onclick="buyRecommendation('${esc(item.recommendation_id)}')">${liveState.live_execution_enabled ? 'BUY' : 'LIVE OFF'}</button><button class="secondary" onclick="skipRecommendation('${esc(item.recommendation_id)}')">SKIP</button></div></div>`).join('');
  modal.classList.add('open');
}

function closeAlertModal() {
  $('buyAlertModal')?.classList.remove('open');
}

async function buyRecommendation(recommendationId) {
  const recommendation = Object.values(liveState.recommendations).find(item => item.recommendation_id === recommendationId);
  if (!recommendation || isExpired(recommendation)) {
    alert('This opportunity expired. Wait for the next scan.');
    return;
  }
  if (!liveState.live_execution_enabled) {
    alert('Live execution is disabled. Keep paper mode on until broker authentication and paper validation are complete.');
    return;
  }
  const message = `Send REAL Groww INTRADAY BUY order?\n\n${recommendation.symbol} (${recommendation.exchange})\nEntry: ${recommendation.entry_price}\nTarget: ${recommendation.target_price}\nStop loss: ${recommendation.stop_loss}\nQuantity: ${recommendation.quantity}\nConfidence: ${Number(recommendation.confidence || 0).toFixed(0)}%\n\nThe backend will re-run the agents and re-check the live quote before submitting.`;
  if (!confirm(message)) return;

  try {
    const response = await fetchWithTimeout(`${backendHttp()}/api/orders/buy-recommendation`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({recommendation_id: recommendationId}),
    }, 15000);
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || 'Order was blocked.');
    closeAlertModal();
    const order = data.order || {};
    alert(`Groww intraday order submitted.\nOrder ID: ${order.groww_order_id || 'See broker response'}\nStatus: ${order.order_status || 'Submitted'}\n\nTarget and stop are monitored recommendations; linked exit orders are not yet automatic.`);
  } catch (error) {
    alert(`Order not submitted: ${error.name === 'AbortError' ? 'Request timed out.' : error.message}`);
  }
}

async function scanNow() {
  const button = $('scanNowButton');
  if (button) { button.disabled = true; button.textContent = 'SCANNING…'; }
  try {
    const response = await fetchWithTimeout(`${backendHttp()}/api/opportunities/scan-now`, {method: 'POST'}, 30000);
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || 'Scan failed');
    applyOpportunitySnapshot(data.items || [], data.market_regime, data.scan_at);
  } catch (error) {
    alert(`Scan failed: ${error.name === 'AbortError' ? 'Request timed out.' : error.message}`);
  } finally {
    if (button) { button.disabled = false; button.textContent = 'SCAN NOW'; }
  }
}

function applyOpportunitySnapshot(items, marketRegime, scanAt) {
  liveState.opportunities = items || [];
  liveState.recommendations = {};
  for (const item of items || []) {
    if (item?.symbol) liveState.recommendations[`${item.exchange || 'NSE'}:${item.symbol}`] = item;
  }
  if (marketRegime) liveState.market_regime = marketRegime;
  if (scanAt) liveState.scan_at = scanAt;
  renderDashboard();
}

function addPosition() {
  const position = {
    symbol: $('pSymbol')?.value.trim().toUpperCase() || '',
    market: $('pMarket')?.value || 'NSE',
    qty: num('pQty'),
    avg: num('pAvg'),
  };
  if (!position.symbol || !(position.qty > 0) || !(position.avg > 0)) {
    alert('Enter a valid symbol, quantity and average price.');
    return;
  }
  portfolio.push(position);
  localStorage.setItem('pai_portfolio', JSON.stringify(portfolio));
  $('pSymbol').value = '';
  $('pQty').value = '';
  $('pAvg').value = '';
  renderPortfolio();
}

function removePosition(index) {
  portfolio.splice(index, 1);
  localStorage.setItem('pai_portfolio', JSON.stringify(portfolio));
  renderPortfolio();
}

function evaluateTrade() {
  const direction = $('direction').value;
  const current = num('currentPrice');
  const reference = num('referencePrice');
  const entry = num('entryPrice');
  const stop = num('stopLoss');
  const target = num('targetPrice');
  const quantity = num('quantity');
  const capital = num('portfolioValue');
  const quoteAge = Math.max(0, num('quoteAge'));
  const sources = num('sourceCount');
  const reasons = [];

  if (!$('symbol').value.trim()) reasons.push('Symbol is required.');
  if (![current, reference, entry, stop, target, quantity, capital].every(value => value > 0)) reasons.push('All price, quantity, and portfolio values must be greater than zero.');
  if (quoteAge > policy.maxPriceAgeSeconds) reasons.push(`Quote is stale (${quoteAge}s; maximum ${policy.maxPriceAgeSeconds}s).`);
  if (sources < policy.minConfirmationSources) reasons.push(`Insufficient confirmation sources (${sources}; minimum ${policy.minConfirmationSources}).`);

  const missing = [];
  if (!checked('newsChecked')) missing.push('news');
  if (!checked('technicalChecked')) missing.push('technical');
  if (!checked('portfolioChecked')) missing.push('portfolio');
  if (missing.length) reasons.push(`Missing confirmations: ${missing.join(', ')}.`);
  if (checked('liveRequested') && !policy.allowLiveExecution) reasons.push('Manual live execution is disabled. The evaluator is decision support only.');

  let risk = 0;
  let reward = 0;
  if (direction === 'long') {
    if (!(stop < entry && entry < target)) reasons.push('Long setup must satisfy stop loss < entry < target.');
    risk = entry - stop;
    reward = target - entry;
  } else {
    if (!(target < entry && entry < stop)) reasons.push('Short setup must satisfy target < entry < stop loss.');
    risk = stop - entry;
    reward = entry - target;
  }

  const rewardRisk = risk > 0 && reward > 0 ? reward / risk : 0;
  if (rewardRisk < policy.minRewardRiskRatio) reasons.push(`Reward/risk ${rewardRisk.toFixed(2)} is below minimum ${Number(policy.minRewardRiskRatio).toFixed(2)}.`);
  const positionRisk = Math.max(0, risk) * Math.max(0, quantity);
  const riskPct = capital > 0 ? positionRisk / capital * 100 : 0;
  if (riskPct > policy.maxRiskPerTradePct) reasons.push(`Position risks ${riskPct.toFixed(2)}% of portfolio; maximum ${Number(policy.maxRiskPerTradePct).toFixed(2)}%.`);

  let chase = 0;
  if (reference > 0) {
    chase = direction === 'long' ? (current - reference) / reference * 100 : (reference - current) / reference * 100;
    if (chase > policy.maxChasePct) reasons.push(`Do not chase: ${chase.toFixed(2)}% beyond reference; maximum ${Number(policy.maxChasePct).toFixed(2)}%.`);
  }

  evaluations += 1;
  localStorage.setItem('pai_evaluations', String(evaluations));
  const eligible = reasons.length === 0;
  const action = eligible ? (direction === 'long' ? 'BUY' : 'SELL') : 'WAIT';
  $('decisionBox').className = `decision ${eligible ? 'good' : 'wait'}`;
  $('decisionBox').querySelector('strong').textContent = action;
  $('decisionText').textContent = eligible ? 'Setup passes the configured local guardrails.' : 'Setup does not pass the configured guardrails.';
  $('rr').textContent = rewardRisk.toFixed(2);
  $('riskPct').textContent = `${riskPct.toFixed(3)}%`;
  $('chasePct').textContent = `${chase.toFixed(3)}%`;
  $('positionRisk').textContent = positionRisk.toFixed(2);
  $('reasons').innerHTML = '';
  const messages = eligible
    ? ['All configured local guardrails passed.', 'Automatic live orders use the separate backend agentic scanner and server-side revalidation.']
    : reasons;
  for (const message of messages) {
    const li = document.createElement('li');
    li.textContent = message;
    $('reasons').appendChild(li);
  }
  renderDashboard();
}

function setValues(values) {
  for (const [key, value] of Object.entries(values)) {
    if ($(key)) $(key).value = value;
  }
}

function loadValid(runEvaluation = true) {
  setValues({symbol:'RELIANCE',market:'NSE',direction:'long',currentPrice:101,referencePrice:100,entryPrice:101,stopLoss:99,targetPrice:105,quantity:10,portfolioValue:100000,quoteAge:0,sourceCount:2});
  ['newsChecked','technicalChecked','portfolioChecked'].forEach(id => { $(id).checked = true; });
  $('liveRequested').checked = false;
  if (runEvaluation) evaluateTrade();
}

function loadRejected() {
  setValues({symbol:'TEST',market:'NSE',direction:'long',currentPrice:104,referencePrice:100,entryPrice:104,stopLoss:99,targetPrice:108,quantity:500,portfolioValue:100000,quoteAge:180,sourceCount:1});
  $('newsChecked').checked = false;
  $('technicalChecked').checked = true;
  $('portfolioChecked').checked = true;
  $('liveRequested').checked = true;
  evaluateTrade();
}

const brokers = ['Groww'];
if ($('brokerCards')) {
  $('brokerCards').innerHTML = brokers.map(name => `<div class="broker"><div><b>${name}</b><div class="muted">Backend API integration</div></div><button class="secondary" onclick="showBrokerInfo('${name}')">Connection info</button></div>`).join('');
}

function showBrokerInfo(name) {
  $('brokerInfo').innerHTML = `<b>${esc(name)}</b><br>Official broker API runs only in the backend. Secrets remain in backend/.env and are never stored in this page. Live execution stays disabled until explicitly enabled after paper-mode validation.`;
}

function loadSettings() {
  $('sRisk').value = policy.maxRiskPerTradePct;
  $('sRR').value = policy.minRewardRiskRatio;
  $('sChase').value = policy.maxChasePct;
  $('sQuoteAge').value = policy.maxPriceAgeSeconds;
  $('sSources').value = policy.minConfirmationSources;
  $('aiModel').value = localAi.model;
  $('aiBaseUrl').value = localAi.baseUrl;
}

function saveSettings() {
  const next = {
    ...policy,
    maxRiskPerTradePct: num('sRisk'),
    minRewardRiskRatio: num('sRR'),
    maxChasePct: num('sChase'),
    maxPriceAgeSeconds: num('sQuoteAge'),
    minConfirmationSources: num('sSources'),
  };
  if (!(next.maxRiskPerTradePct > 0 && next.maxRiskPerTradePct <= 5)) return alert('Max risk must be greater than 0 and no more than 5%.');
  if (!(next.minRewardRiskRatio >= 1)) return alert('Minimum reward/risk must be at least 1.0.');
  if (!(next.maxChasePct >= 0 && next.maxChasePct <= 10)) return alert('Max chase must be between 0 and 10%.');
  if (!(next.maxPriceAgeSeconds >= 1)) return alert('Max quote age must be at least 1 second.');
  if (!(next.minConfirmationSources >= 1)) return alert('At least one confirmation source is required.');
  policy = next;
  localStorage.setItem('pai_policy', JSON.stringify(policy));
  alert('Local evaluator settings saved. Live scanner risk settings remain authoritative on the backend in backend/.env.');
}

function saveLocalAiSettings() {
  const model = $('aiModel').value.trim();
  const baseUrl = $('aiBaseUrl').value.trim().replace(/\/$/, '');
  if (!model || !/^https?:\/\//.test(baseUrl)) {
    alert('Enter a valid local Ollama model and a URL such as http://127.0.0.1:11434.');
    return;
  }
  localAi = {enabled: true, model, baseUrl};
  localStorage.setItem('pai_local_ai', JSON.stringify(localAi));
  checkLocalAi(true);
}

function clearLocalData() {
  if (typeof clearAllPrivateLocalData === 'function') {
    clearAllPrivateLocalData();
    return;
  }
  if (!confirm('Clear all locally saved portfolio, settings, local AI settings, and skipped signals?')) return;
  ['pai_policy','pai_local_ai','pai_portfolio','pai_evaluations'].forEach(key => localStorage.removeItem(key));
  sessionStorage.removeItem('pai_skipped_signals');
  location.reload();
}

async function checkLocalAi(showAlert = false) {
  const dashboard = $('localAiStatus');
  const settings = $('localAiSettingsStatus');
  const setStatus = (text, ok) => {
    if (dashboard) { dashboard.textContent = text; dashboard.className = ok ? '' : 'off'; }
    if (settings) { settings.className = ok ? 'safe' : 'warn'; settings.innerHTML = `<b>${ok ? 'Local AI ready' : 'Local AI unavailable'}</b><br>${esc(text)}`; }
  };

  try {
    const response = await fetchWithTimeout(`${localAi.baseUrl}/api/tags`, {}, 2500);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    const names = (data.models || []).map(model => model.name);
    const exact = names.includes(localAi.model) || names.some(name => name.split(':')[0] === localAi.model.split(':')[0]);
    if (!exact) {
      setStatus(`Ollama online · pull ${localAi.model}`, false);
      if (showAlert) alert(`Ollama is running, but ${localAi.model} is not installed. Run: ollama pull ${localAi.model}`);
      return false;
    }
    setStatus(`${localAi.model} · READY`, true);
    if (showAlert) alert(`Local AI is ready: ${localAi.model}`);
    return true;
  } catch (error) {
    setStatus('OFFLINE', false);
    if (showAlert) alert(`Local AI is not reachable at ${localAi.baseUrl}. Start Ollama on this Mac and try again.\n\n${error.name === 'AbortError' ? 'Connection timed out.' : error.message}`);
    return false;
  }
}

function closeLocalAiModal() {
  $('localAiModal')?.classList.remove('open');
}

async function reviewWithLocalAI(recommendationId) {
  const recommendation = Object.values(liveState.recommendations).find(item => item.recommendation_id === recommendationId);
  if (!recommendation) return alert('Opportunity not found.');
  const modal = $('localAiModal');
  const title = $('localAiTitle');
  const body = $('localAiBody');
  if (!modal || !title || !body) return;

  title.textContent = `Local AI review: ${recommendation.symbol}`;
  body.innerHTML = `<div class="muted">Running ${esc(localAi.model)} locally on this Mac. The deterministic ${esc(recommendation.state || recommendation.action)} decision remains authoritative.</div><p>Reviewing…</p>`;
  modal.classList.add('open');

  const snapshot = {
    symbol: recommendation.symbol,
    exchange: recommendation.exchange,
    deterministic_state: recommendation.state || recommendation.action,
    confidence: recommendation.confidence,
    entry_price: recommendation.entry_price,
    target_price: recommendation.target_price,
    stop_loss: recommendation.stop_loss,
    quantity: recommendation.quantity,
    reward_risk_ratio: recommendation.reward_risk_ratio,
    day_change_pct: recommendation.day_change_pct,
    intraday_range_pct: recommendation.intraday_range_pct,
    range_position: recommendation.range_position,
    spread_pct: recommendation.spread_pct,
    buy_pressure: recommendation.buy_pressure,
    market_regime: liveState.market_regime,
    agent_scores: recommendation.agent_scores,
    risk_vetoes: recommendation.risk_vetoes,
    reasons: recommendation.reasons,
    generated_at: recommendation.generated_at,
    valid_for_seconds: recommendation.valid_for_seconds,
  };
  const system = 'You are the private local AI reviewer inside a safety-first trading decision-support app. You are advisory only. Never override the deterministic decision, never invent live prices or news, never ask for passwords, OTPs, PINs, recovery codes, API secrets, broker credentials, or bank information, and never suggest bypassing a risk veto. Review only the supplied snapshot. Be concise and use these headings: Decision context, Strongest evidence, Main risks, What would invalidate the setup. Explicitly state when data is missing or stale.';

  try {
    const response = await fetchWithTimeout(`${localAi.baseUrl}/api/chat`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        model: localAi.model,
        stream: false,
        keep_alive: '10m',
        messages: [
          {role: 'system', content: system},
          {role: 'user', content: `Review this machine-generated trade snapshot. Do not change its deterministic state.\n\n${JSON.stringify(snapshot, null, 2)}`},
        ],
        options: {temperature: 0.2, num_ctx: 4096},
      }),
    }, 120000);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    const content = data.message?.content || 'No review returned.';
    body.innerHTML = `<div class="warn"><b>Advisory only</b><br>The local LLM cannot change BUY / WAIT logic or place an order.</div><div style="white-space:pre-wrap;margin-top:14px">${esc(content)}</div>`;
    checkLocalAi(false);
  } catch (error) {
    body.innerHTML = `<div class="warn"><b>Local AI review failed</b><br>${esc(error.name === 'AbortError' ? 'The local model timed out.' : error.message)}<br><br>Start Ollama and make sure the selected model is installed.</div>`;
  }
}

async function hydrateLiveState() {
  try {
    const response = await fetchWithTimeout(`${backendHttp()}/api/live/state`, {}, 5000);
    if (!response.ok) return;
    const state = await response.json();
    liveState = {...liveState, ...state};
    if (Array.isArray(state.opportunities)) applyOpportunitySnapshot(state.opportunities, state.market_regime, state.scan_at);
    renderPortfolio();
    renderNews();
    renderRecommendations();
  } catch (_) {
    // The websocket reconnect loop will keep trying while the local backend starts.
  }
}

function handleLiveEvent(message) {
  liveState.lastEvent = message.ts || new Date().toISOString();
  if (message.type === 'snapshot') {
    liveState.recommendations = message.recommendations || liveState.recommendations;
    liveState.opportunities = message.opportunities || Object.values(liveState.recommendations);
    liveState.holdings = message.holdings || liveState.holdings;
    liveState.positions = message.positions || liveState.positions;
    liveState.live_execution_enabled = Boolean(message.live_execution_enabled);
    liveState.market_regime = message.market_regime || liveState.market_regime;
    liveState.scan_at = message.scan_at || liveState.scan_at;
  } else if (message.type === 'opportunities') {
    applyOpportunitySnapshot(message.items || [], message.market_regime, message.scan_at);
  } else if (message.type === 'buy_alert') {
    showBuyAlert(message.items || []);
  } else if (message.type === 'portfolio') {
    liveState.holdings = message.holdings || liveState.holdings;
    liveState.positions = message.positions || liveState.positions;
  } else if (message.type === 'order') {
    liveState.orders.unshift(message.data);
  } else if (message.type === 'news') {
    liveState.news = message.items || [];
  } else if (message.type === 'scanner_error') {
    const status = $('liveStatus');
    if (status) {
      status.className = 'warn';
      status.innerHTML = `<b>Scanner error</b><br>${esc(message.message || 'Unknown error')}`;
    }
  }
  renderPortfolio();
  renderNews();
  renderRecommendations();
  renderOpportunityCount();
}

function connectLive() {
  clearTimeout(reconnectTimer);
  try {
    liveSocket = new WebSocket(backendWs());
    liveSocket.onopen = () => {
      liveState.connected = true;
      renderLiveStatus();
      hydrateLiveState();
    };
    liveSocket.onmessage = event => {
      try { handleLiveEvent(JSON.parse(event.data)); } catch (_) { /* ignore malformed local event */ }
    };
    liveSocket.onerror = () => liveSocket.close();
    liveSocket.onclose = () => {
      liveState.connected = false;
      renderLiveStatus();
      reconnectTimer = setTimeout(connectLive, 1500);
    };
  } catch (_) {
    reconnectTimer = setTimeout(connectLive, 1500);
  }
}

function initializeNavigation() {
  document.querySelectorAll('.nav button').forEach(button => button.addEventListener('click', () => {
    document.querySelectorAll('.nav button').forEach(item => item.classList.remove('active'));
    document.querySelectorAll('.section').forEach(section => section.classList.remove('active'));
    button.classList.add('active');
    $(button.dataset.section)?.classList.add('active');
  }));
}

function initializeApp() {
  initializeNavigation();
  window.addEventListener('click', event => {
    if (event.target === $('buyAlertModal')) closeAlertModal();
    if (event.target === $('localAiModal')) closeLocalAiModal();
  });
  renderPortfolio();
  loadSettings();
  loadValid(false);
  renderNews();
  renderRecommendations();
  checkLocalAi(false);
  connectLive();
  setInterval(() => { renderRecommendations(); renderOpportunityCount(); }, 1000);
  setInterval(() => checkLocalAi(false), 30000);
}

initializeApp();
