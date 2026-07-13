(() => {
  'use strict';

  const GTT_KEY = 'pai_gtt_plans';
  const JOURNAL_KEY = 'pai_trade_journal';
  const DEFAULT_POLICY = {maxRiskPerTradePct:1,minRewardRiskRatio:2,maxChasePct:1.5,maxPriceAgeSeconds:120,minConfirmationSources:2};

  const byId = id => document.getElementById(id);
  const numberValue = id => Number(byId(id)?.value || 0);
  const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[char]));
  const loadJson = (key, fallback) => {
    try { return JSON.parse(localStorage.getItem(key) || 'null') ?? fallback; }
    catch (_) { return fallback; }
  };
  const saveJson = (key, value) => localStorage.setItem(key, JSON.stringify(value));
  const id = () => (globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`);
  const money = value => new Intl.NumberFormat('en-IN',{style:'currency',currency:'INR',maximumFractionDigits:2}).format(Number(value)||0);

  let gttPlans = loadJson(GTT_KEY, []);
  let journalEntries = loadJson(JOURNAL_KEY, []);

  function currentPolicy() {
    return {...DEFAULT_POLICY, ...loadJson('pai_policy', {})};
  }

  function renderGttPlans() {
    const body = byId('gttRows');
    if (!body) return;
    if (!gttPlans.length) {
      body.innerHTML = '<tr><td colspan="8" class="muted">No local GTT plans saved.</td></tr>';
      return;
    }
    body.innerHTML = gttPlans.slice().reverse().map(plan => `
      <tr>
        <td>${escapeHtml(plan.symbol)}<div class="muted">${escapeHtml(plan.market)}</div></td>
        <td>${escapeHtml(plan.direction === 'long' ? 'BUY' : 'SELL')}</td>
        <td>${money(plan.entry)}</td>
        <td>${money(plan.target)}</td>
        <td>${money(plan.stop)}</td>
        <td>${Number(plan.rewardRisk).toFixed(2)}</td>
        <td>${Number(plan.riskPct).toFixed(3)}%</td>
        <td><button class="secondary" onclick="removeGttPlan('${escapeHtml(plan.id)}')">Remove</button></td>
      </tr>`).join('');
  }

  globalThis.clearGttForm = function clearGttForm() {
    ['gttSymbol','gttEntry','gttStop','gttTarget','gttQty','gttNote'].forEach(field => { if (byId(field)) byId(field).value = ''; });
    const validation = byId('gttValidation');
    if (validation) validation.innerHTML = '<b>No GTT plan evaluated yet.</b>';
  };

  globalThis.saveGttPlan = function saveGttPlan() {
    const policy = currentPolicy();
    const symbol = byId('gttSymbol')?.value.trim().toUpperCase() || '';
    const market = byId('gttMarket')?.value || 'NSE';
    const direction = byId('gttDirection')?.value || 'long';
    const entry = numberValue('gttEntry');
    const stop = numberValue('gttStop');
    const target = numberValue('gttTarget');
    const quantity = numberValue('gttQty');
    const capital = numberValue('gttCapital');
    const note = byId('gttNote')?.value.trim() || '';
    const reasons = [];

    if (!symbol) reasons.push('Symbol is required.');
    if (![entry, stop, target, quantity, capital].every(value => value > 0)) reasons.push('Entry, stop, target, quantity, and portfolio value must be greater than zero.');

    let riskPerShare = 0;
    let rewardPerShare = 0;
    if (direction === 'long') {
      if (!(stop < entry && entry < target)) reasons.push('Long plan must satisfy stop < entry < target.');
      riskPerShare = entry - stop;
      rewardPerShare = target - entry;
    } else {
      if (!(target < entry && entry < stop)) reasons.push('Short plan must satisfy target < entry < stop.');
      riskPerShare = stop - entry;
      rewardPerShare = entry - target;
    }

    const rewardRisk = riskPerShare > 0 ? rewardPerShare / riskPerShare : 0;
    const positionRisk = Math.max(0, riskPerShare) * Math.max(0, quantity);
    const riskPct = capital > 0 ? positionRisk / capital * 100 : 0;
    if (rewardRisk < policy.minRewardRiskRatio) reasons.push(`Reward/risk ${rewardRisk.toFixed(2)} is below the minimum ${Number(policy.minRewardRiskRatio).toFixed(2)}.`);
    if (riskPct > policy.maxRiskPerTradePct) reasons.push(`Position risk ${riskPct.toFixed(3)}% exceeds the ${Number(policy.maxRiskPerTradePct).toFixed(2)}% limit.`);

    const validation = byId('gttValidation');
    if (reasons.length) {
      if (validation) validation.innerHTML = `<b>WAIT — plan not saved</b><br>${reasons.map(escapeHtml).join('<br>')}`;
      return;
    }

    gttPlans.push({id:id(),createdAt:new Date().toISOString(),symbol,market,direction,entry,stop,target,quantity,capital,note,rewardRisk,riskPct,status:'PLANNED_REVALIDATION_REQUIRED'});
    saveJson(GTT_KEY, gttPlans);
    if (validation) validation.className = 'safe';
    if (validation) validation.innerHTML = `<b>Plan saved locally</b><br>R:R ${rewardRisk.toFixed(2)} · Risk ${riskPct.toFixed(3)}%. Fresh live validation is mandatory before any future broker submission.`;
    renderGttPlans();
  };

  globalThis.removeGttPlan = function removeGttPlan(planId) {
    gttPlans = gttPlans.filter(plan => plan.id !== planId);
    saveJson(GTT_KEY, gttPlans);
    renderGttPlans();
  };

  function renderJournal() {
    const body = byId('journalRows');
    if (!body) return;
    if (!journalEntries.length) {
      body.innerHTML = '<tr><td colspan="6" class="muted">No journal entries saved.</td></tr>';
      return;
    }
    body.innerHTML = journalEntries.slice().reverse().slice(0,100).map(entry => `
      <tr>
        <td>${escapeHtml(new Date(entry.createdAt).toLocaleString('en-IN'))}</td>
        <td>${escapeHtml(entry.symbol)}</td>
        <td>${escapeHtml(entry.outcome)}</td>
        <td>${escapeHtml(entry.rule || '—')}</td>
        <td>${escapeHtml(entry.note || '—')}</td>
        <td><button class="secondary" onclick="removeJournalEntry('${escapeHtml(entry.id)}')">Remove</button></td>
      </tr>`).join('');
  }

  globalThis.saveJournalEntry = function saveJournalEntry() {
    const symbol = byId('journalSymbol')?.value.trim().toUpperCase() || '';
    const outcome = byId('journalOutcome')?.value || 'Missed';
    const rule = byId('journalRule')?.value.trim() || '';
    const context = byId('journalContext')?.value.trim() || '';
    const note = byId('journalNote')?.value.trim() || '';
    if (!symbol || (!rule && !context && !note)) {
      alert('Enter a symbol and at least one reason, market-context note, or lesson.');
      return;
    }
    journalEntries.push({id:id(),createdAt:new Date().toISOString(),symbol,outcome,rule,context,note});
    saveJson(JOURNAL_KEY, journalEntries);
    ['journalSymbol','journalRule','journalContext','journalNote'].forEach(field => { if (byId(field)) byId(field).value = ''; });
    renderJournal();
  };

  globalThis.removeJournalEntry = function removeJournalEntry(entryId) {
    journalEntries = journalEntries.filter(entry => entry.id !== entryId);
    saveJson(JOURNAL_KEY, journalEntries);
    renderJournal();
  };

  function updateRoutineClock() {
    const clock = byId('routineClock');
    const status = byId('routineStatus');
    if (!clock || !status) return;

    const parts = Object.fromEntries(new Intl.DateTimeFormat('en-GB', {
      timeZone:'Asia/Kolkata', weekday:'short', hour:'2-digit', minute:'2-digit', second:'2-digit', hour12:false
    }).formatToParts(new Date()).filter(part => part.type !== 'literal').map(part => [part.type, part.value]));
    const hour = Number(parts.hour);
    const minute = Number(parts.minute);
    const minutes = hour * 60 + minute;
    const weekday = parts.weekday;
    const isWeekend = weekday === 'Sat' || weekday === 'Sun';

    clock.querySelector('strong').textContent = `${parts.hour}:${parts.minute}:${parts.second}`;
    clock.querySelector('span').textContent = `${weekday} · Asia/Kolkata`;

    let title = 'Pre-market preparation';
    let detail = 'Review overnight news and prepare the 08:00 call sheet. Do not create an actionable trade without fresh market data.';
    if (isWeekend) {
      title = 'Market closed — review mode';
      detail = 'Use the journal, review rules, and prepare research. Do not treat stale quotes as live opportunities.';
    } else if (minutes >= 480 && minutes < 555) {
      title = '08:00 call-sheet window';
      detail = 'Build the watch universe and hypotheses. Orders still require current live quotes and later revalidation.';
    } else if (minutes >= 555 && minutes < 560) {
      title = 'Opening volatility caution';
      detail = 'The market is open. Avoid impulsive entries and let the first price action establish itself.';
    } else if (minutes >= 560 && minutes < 565) {
      title = '09:20 first opening recheck';
      detail = 'Recheck live price, spread, market regime, news, and portfolio exposure.';
    } else if (minutes >= 565 && minutes < 660) {
      title = '09:25+ active revalidation window';
      detail = 'Use fresh quotes only. A valid setup can still be vetoed by risk, spread, regime, exposure, or anti-chase rules.';
    } else if (minutes >= 660 && minutes <= 920) {
      title = 'Post-11:00 slowdown advisory';
      detail = 'Opportunities may slow down. Do not force trades; continue to require the same confidence and risk checks.';
    } else if (minutes > 920) {
      title = 'Post-market review';
      detail = 'Review executions, skipped trades, missed moves, and rule adherence. Regret is not a reason to weaken tomorrow’s controls.';
    }

    status.innerHTML = `<b>${escapeHtml(title)}</b><br>${escapeHtml(detail)}`;
  }

  async function loadRulesContract() {
    const status = byId('rulesContractStatus');
    const summary = byId('researchSourceSummary');
    try {
      const response = await fetch('config/trading_rules.json', {cache:'no-store'});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const rules = await response.json();
      if (status) {
        status.className = 'safe';
        status.innerHTML = `<b>Rules contract ${escapeHtml(rules.schema_version)} loaded</b><br>Paper default · live revalidation · max risk ${Number(rules.risk.max_risk_per_trade_pct).toFixed(1)}% · min R:R ${Number(rules.risk.min_reward_risk_ratio).toFixed(1)} · anti-chase ${Number(rules.risk.max_chase_pct).toFixed(1)}%.`;
      }
      if (summary) {
        const screeners = rules.research_sources?.screeners || [];
        const news = rules.research_sources?.news || [];
        summary.innerHTML = `<p><b>Research registry:</b> ${screeners.map(escapeHtml).join(', ')}</p><p><b>News registry:</b> ${news.map(escapeHtml).join(', ')}</p><p>Provider names are a research registry, not proof of a live connection. Unconnected news remains neutral.</p>`;
      }
    } catch (error) {
      if (status) status.innerHTML = `<b>Rules contract unavailable</b><br>${escapeHtml(error.message)}`;
    }
  }

  function applyMacRuntime() {
    const runtime = globalThis.PAI_RUNTIME || {};
    if (!runtime.ollamaModel && !runtime.ollamaBaseUrl) return;
    try {
      const existing = loadJson('pai_local_ai', null);
      if (!existing) {
        const next = {
          enabled:true,
          model:runtime.ollamaModel || 'gpt-oss:20b',
          baseUrl:(runtime.ollamaBaseUrl || 'http://127.0.0.1:11434').replace(/\/$/,'')
        };
        localStorage.setItem('pai_local_ai', JSON.stringify(next));
        if (typeof localAi !== 'undefined') localAi = next;
        if (byId('aiModel')) byId('aiModel').value = next.model;
        if (byId('aiBaseUrl')) byId('aiBaseUrl').value = next.baseUrl;
        if (typeof checkLocalAi === 'function') checkLocalAi(false);
      }
    } catch (_) {
      // Runtime hints are optional; the app remains usable without them.
    }
  }

  globalThis.clearAllPrivateLocalData = function clearAllPrivateLocalData() {
    if (!confirm('Clear locally saved portfolio, evaluator settings, GTT plans, journal entries, AI settings, evaluation counts, and skipped signals?')) return;
    ['pai_policy','pai_local_ai','pai_portfolio','pai_evaluations',GTT_KEY,JOURNAL_KEY].forEach(key => localStorage.removeItem(key));
    sessionStorage.removeItem('pai_skipped_signals');
    location.reload();
  };

  renderGttPlans();
  renderJournal();
  updateRoutineClock();
  setInterval(updateRoutineClock, 1000);
  loadRulesContract();
  applyMacRuntime();
})();
