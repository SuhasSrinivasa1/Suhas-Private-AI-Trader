const DEFAULT_POLICY={enabled:true,allowLiveExecution:false,maxRiskPerTradePct:1,minRewardRiskRatio:2,maxChasePct:1.5,maxPriceAgeSeconds:120,minConfirmationSources:2};
let policy=JSON.parse(localStorage.getItem('pai_policy')||'null')||{...DEFAULT_POLICY};
let portfolio=JSON.parse(localStorage.getItem('pai_portfolio')||'[]');
let evaluations=Number(localStorage.getItem('pai_evaluations')||'0');
let liveState={connected:false,lastEvent:null,prices:{},news:[],holdings:[],positions:[],orders:[],recommendations:{},opportunities:[],live_execution_enabled:false,market_regime:{score:50,label:'neutral'},scan_at:null,scanner_universe_size:0};
let liveSocket=null,reconnectTimer=null;
const skippedSignals=new Set(JSON.parse(sessionStorage.getItem('pai_skipped_signals')||'[]'));

const $=id=>document.getElementById(id),num=id=>Number($(id).value),checked=id=>$(id).checked;
const money=n=>new Intl.NumberFormat('en-IN',{style:'currency',currency:'INR',maximumFractionDigits:2}).format(Number(n)||0);
const pct=n=>`${Number(n||0).toFixed(2)}%`;
const backendHttp=()=>`${location.protocol==='https:'?'https':'http'}://${location.hostname||'127.0.0.1'}:8000`;
const backendWs=()=>`${location.protocol==='https:'?'wss':'ws'}://${location.hostname||'127.0.0.1'}:8000/ws/live`;
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]));

function saveSkipped(){sessionStorage.setItem('pai_skipped_signals',JSON.stringify([...skippedSignals]));}
function isExpired(r){if(!r?.generated_at)return false;const age=(Date.now()-new Date(r.generated_at).getTime())/1000;return age>Number(r.valid_for_seconds||20)}
function signalAge(r){if(!r?.generated_at)return '—';return `${Math.max(0,Math.floor((Date.now()-new Date(r.generated_at).getTime())/1000))}s`}
function latestPrice(symbol){const key=Object.keys(liveState.prices).find(k=>k.endsWith(`:${symbol}`)||k===symbol);const event=key?liveState.prices[key]:null;return event?.ltp??event?.price??event?.last_price??null}

function playAlert(){try{const ctx=new (window.AudioContext||window.webkitAudioContext)();const osc=ctx.createOscillator();const gain=ctx.createGain();osc.connect(gain);gain.connect(ctx.destination);osc.frequency.value=880;gain.gain.setValueAtTime(.08,ctx.currentTime);gain.gain.exponentialRampToValueAtTime(.001,ctx.currentTime+.35);osc.start();osc.stop(ctx.currentTime+.35)}catch(_){}}

function renderDashboard(){
  const source=liveState.holdings.length?liveState.holdings:portfolio;
  const value=source.reduce((s,p)=>{const symbol=p.trading_symbol||p.symbol||p.tradingsymbol||'';const qty=Number(p.quantity??p.qty??0);const avg=Number(p.average_price??p.avg??p.averagePrice??0);const lp=latestPrice(symbol);return s+qty*(Number(lp)||avg)},0);
  $('kpiPortfolio').textContent=money(value);
  $('kpiPositions').textContent=(liveState.positions.length||source.length);
  $('kpiEvaluations').textContent=evaluations;
  const execution=$('liveExecutionStatus');if(execution){execution.textContent=liveState.live_execution_enabled?'ON':'OFF';execution.className=liveState.live_execution_enabled?'':'off'}
  const regime=$('marketRegime');if(regime)regime.textContent=`${String(liveState.market_regime?.label||'neutral').toUpperCase()} · ${Number(liveState.market_regime?.score||50).toFixed(0)}`;
  const scanned=$('scannerUniverse');if(scanned)scanned.textContent=String(liveState.scanner_universe_size||0);
  $('dashboardPositions').innerHTML=source.length?source.slice(-8).reverse().map(p=>{const symbol=p.trading_symbol||p.symbol||p.tradingsymbol||'';const market=p.exchange||p.market||'NSE';const qty=Number(p.quantity??p.qty??0);const avg=Number(p.average_price??p.avg??p.averagePrice??0);const lp=latestPrice(symbol);return `<tr><td>${esc(symbol)}</td><td>${esc(market)}</td><td>${qty}</td><td>${avg||'—'}</td><td>${lp?money(qty*lp):money(qty*avg)}</td></tr>`}).join(''):'<tr><td colspan="5" class="muted">No positions saved.</td></tr>';
  renderLiveStatus();renderRecommendations();renderOpportunityCount();
}

function renderPortfolio(){$('portfolioRows').innerHTML=portfolio.length?portfolio.map((p,i)=>`<tr><td>${esc(p.symbol)}</td><td>${esc(p.market)}</td><td>${p.qty}</td><td>${p.avg}</td><td>${money(p.qty*(latestPrice(p.symbol)||p.avg))}</td><td><button class="secondary" onclick="removePosition(${i})">Remove</button></td></tr>`).join(''):'<tr><td colspan="6" class="muted">No positions saved.</td></tr>';renderDashboard()}
function renderLiveStatus(){const status=$('liveStatus');if(!status)return;status.className=liveState.connected?'safe':'warn';status.innerHTML=`<b>${liveState.connected?'Agentic scanner connected':'Scanner disconnected'}</b><br>${liveState.scan_at?`Last scan: ${new Date(liveState.scan_at).toLocaleTimeString()}`:liveState.lastEvent?`Last event: ${new Date(liveState.lastEvent).toLocaleTimeString()}`:'Waiting for backend events.'}`}
function renderNews(){const box=$('liveNews');if(!box)return;box.innerHTML=liveState.news.length?liveState.news.slice(0,12).map(n=>`<div class="broker"><div><b>${esc(n.title||'Headline')}</b><div class="muted">${esc(n.source||'')}${n.published?` · ${esc(n.published)}`:''}</div></div></div>`).join(''):'<div class="muted">News agent is neutral until a configured news provider is connected; it does not invent sentiment.</div>'}
function renderOpportunityCount(){const el=$('opportunityCount');if(!el)return;const buys=Object.values(liveState.recommendations||{}).filter(r=>r.state==='BUY'&&!isExpired(r)&&!skippedSignals.has(r.recommendation_id));el.textContent=String(buys.length)}

function sortedRecommendations(){return Object.values(liveState.recommendations||{}).filter(r=>!isExpired(r)).sort((a,b)=>((b.state==='BUY')-(a.state==='BUY'))||((b.state==='WATCHING')-(a.state==='WATCHING'))||Number(b.rank_score||b.confidence||0)-Number(a.rank_score||a.confidence||0))}

function renderRecommendations(){
  const board=$('recommendationBoard');if(!board)return;
  const items=sortedRecommendations();
  if(!items.length){board.innerHTML='<div class="muted">Scanner is running. No current opportunity has passed the ranking threshold.</div>';return}
  board.innerHTML=items.map((r,index)=>{
    const isBuy=r.state==='BUY';const skipped=skippedSignals.has(r.recommendation_id);const canExecute=isBuy&&!skipped&&liveState.live_execution_enabled;
    const reasons=(r.reasons||[]).slice(0,3).map(esc).join(' · ');const veto=(r.risk_vetoes||[]).slice(0,2).map(esc).join(' · ');
    return `<div class="opportunity-card ${isBuy?'buy-opportunity':r.state==='WATCHING'?'watch-opportunity':''}">
      <div class="rank-badge">#${index+1}</div>
      <div class="opportunity-main">
        <div class="opportunity-title"><b>${esc(r.symbol)}</b><span class="state-pill ${String(r.state||'WAIT').toLowerCase()}">${esc(r.state||r.action)}</span><span class="confidence">${Number(r.confidence||0).toFixed(0)}% confidence</span></div>
        <div class="price-grid"><span><small>Buy</small><b>${money(r.entry_price)}</b></span><span><small>Target</small><b>${money(r.target_price)}</b></span><span><small>Stop</small><b>${money(r.stop_loss)}</b></span><span><small>Qty</small><b>${Number(r.quantity||0)}</b></span><span><small>R:R</small><b>${Number(r.reward_risk_ratio||0).toFixed(1)}</b></span><span><small>Age</small><b>${signalAge(r)}</b></span></div>
        <div class="agent-row">${Object.entries(r.agent_scores||{}).map(([k,v])=>`<span>${esc(k)} ${Number(v).toFixed(0)}</span>`).join('')}</div>
        <div class="muted">${reasons||veto||'No additional explanation available.'}</div>
        ${veto?`<div class="veto-text">Risk veto: ${veto}</div>`:''}
      </div>
      <div class="opportunity-actions">
        ${isBuy&&!skipped?`<button ${canExecute?'':'disabled'} onclick="buyRecommendation('${esc(r.recommendation_id)}')">${canExecute?'BUY NOW':'LIVE OFF'}</button><button class="secondary" onclick="skipRecommendation('${esc(r.recommendation_id)}')">SKIP</button>`:skipped?'<button class="secondary" disabled>SKIPPED</button>':`<button class="secondary" disabled>${esc(r.state||'WAIT')}</button>`}
      </div>
    </div>`
  }).join('');
}

function skipRecommendation(id){skippedSignals.add(id);saveSkipped();closeAlertModal();renderRecommendations();renderOpportunityCount()}

function showBuyAlert(items){
  const fresh=(items||[]).filter(r=>r.state==='BUY'&&!isExpired(r)&&!skippedSignals.has(r.recommendation_id));if(!fresh.length)return;
  playAlert();
  const modal=$('buyAlertModal'),body=$('buyAlertBody'),title=$('buyAlertTitle');if(!modal||!body||!title)return;
  title.textContent=fresh.length===1?`BUY opportunity: ${fresh[0].symbol}`:`${fresh.length} BUY opportunities detected`;
  body.innerHTML=fresh.map((r,index)=>`<div class="alert-opportunity"><div><b>#${index+1} ${esc(r.symbol)} · ${Number(r.confidence||0).toFixed(0)}%</b><div class="muted">Buy ${money(r.entry_price)} · Target ${money(r.target_price)} · Stop ${money(r.stop_loss)} · Qty ${Number(r.quantity||0)}</div></div><div class="actions"><button ${liveState.live_execution_enabled?'':'disabled'} onclick="buyRecommendation('${esc(r.recommendation_id)}')">${liveState.live_execution_enabled?'BUY':'LIVE OFF'}</button><button class="secondary" onclick="skipRecommendation('${esc(r.recommendation_id)}')">SKIP</button></div></div>`).join('');
  modal.classList.add('open');
}
function closeAlertModal(){const modal=$('buyAlertModal');if(modal)modal.classList.remove('open')}

async function buyRecommendation(recommendationId){
  const rec=Object.values(liveState.recommendations).find(r=>r.recommendation_id===recommendationId);
  if(!rec||isExpired(rec)){alert('This opportunity expired. Wait for the next scan.');return}
  const message=`Send REAL Groww INTRADAY BUY order?\n\n${rec.symbol} (${rec.exchange})\nEntry: ${rec.entry_price}\nTarget: ${rec.target_price}\nStop loss: ${rec.stop_loss}\nQuantity: ${rec.quantity}\nConfidence: ${Number(rec.confidence||0).toFixed(0)}%\n\nThe backend will re-run the agents and re-check the live quote before submitting.`;
  if(!confirm(message))return;
  try{
    const response=await fetch(`${backendHttp()}/api/orders/buy-recommendation`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({recommendation_id:recommendationId})});
    const data=await response.json();if(!response.ok)throw new Error(data.detail||'Order was blocked.');closeAlertModal();
    const order=data.order||{};alert(`Groww intraday order submitted.\nOrder ID: ${order.groww_order_id||'See broker response'}\nStatus: ${order.order_status||'Submitted'}\n\nTarget and stop are monitored recommendations; linked exit orders are not yet automatic.`)
  }catch(err){alert(`Order not submitted: ${err.message}`)}
}

async function scanNow(){const btn=$('scanNowButton');if(btn){btn.disabled=true;btn.textContent='SCANNING…'}try{const r=await fetch(`${backendHttp()}/api/opportunities/scan-now`,{method:'POST'});const data=await r.json();if(!r.ok)throw new Error(data.detail||'Scan failed');applyOpportunitySnapshot(data.items||[],data.market_regime,data.scan_at)}catch(err){alert(`Scan failed: ${err.message}`)}finally{if(btn){btn.disabled=false;btn.textContent='SCAN NOW'}}}

function applyOpportunitySnapshot(items,marketRegime,scanAt){liveState.opportunities=items||[];liveState.recommendations={};for(const r of items||[]){if(r?.symbol)liveState.recommendations[`${r.exchange||'NSE'}:${r.symbol}`]=r}if(marketRegime)liveState.market_regime=marketRegime;if(scanAt)liveState.scan_at=scanAt;renderDashboard()}

function addPosition(){const p={symbol:$('pSymbol').value.trim().toUpperCase(),market:$('pMarket').value,qty:num('pQty'),avg:num('pAvg')};if(!p.symbol||!(p.qty>0)||!(p.avg>0)){alert('Enter a valid symbol, quantity and average price.');return}portfolio.push(p);localStorage.setItem('pai_portfolio',JSON.stringify(portfolio));$('pSymbol').value='';$('pQty').value='';$('pAvg').value='';renderPortfolio()}
function removePosition(i){portfolio.splice(i,1);localStorage.setItem('pai_portfolio',JSON.stringify(portfolio));renderPortfolio()}

function evaluateTrade(){const direction=$('direction').value,current=num('currentPrice'),reference=num('referencePrice'),entry=num('entryPrice'),stop=num('stopLoss'),target=num('targetPrice'),qty=num('quantity'),capital=num('portfolioValue'),quoteAge=num('quoteAge'),sources=num('sourceCount');const reasons=[];if(!$('symbol').value.trim())reasons.push('Symbol is required.');if(quoteAge>policy.maxPriceAgeSeconds)reasons.push(`Quote is stale (${quoteAge}s; maximum ${policy.maxPriceAgeSeconds}s).`);if(sources<policy.minConfirmationSources)reasons.push(`Insufficient confirmation sources (${sources}; minimum ${policy.minConfirmationSources}).`);const missing=[];if(!checked('newsChecked'))missing.push('news');if(!checked('technicalChecked'))missing.push('technical');if(!checked('portfolioChecked'))missing.push('portfolio');if(missing.length)reasons.push('Missing confirmations: '+missing.join(', ')+'.');let risk=0,reward=0;if(direction==='long'){if(!(stop<entry&&entry<target))reasons.push('Long setup must satisfy stop loss < entry < target.');risk=entry-stop;reward=target-entry}else{if(!(target<entry&&entry<stop))reasons.push('Short setup must satisfy target < entry < stop loss.');risk=stop-entry;reward=entry-target}const rr=risk>0&&reward>0?reward/risk:0;if(rr<policy.minRewardRiskRatio)reasons.push(`Reward/risk ${rr.toFixed(2)} is below minimum ${policy.minRewardRiskRatio.toFixed(2)}.`);const positionRisk=Math.max(0,risk)*Math.max(0,qty);const riskPct=capital>0?positionRisk/capital*100:0;if(riskPct>policy.maxRiskPerTradePct)reasons.push(`Position risks ${riskPct.toFixed(2)}% of portfolio; maximum ${policy.maxRiskPerTradePct.toFixed(2)}%.`);let chase=0;if(reference>0){chase=direction==='long'?(current-reference)/reference*100:(reference-current)/reference*100;if(chase>policy.maxChasePct)reasons.push(`Do not chase: ${chase.toFixed(2)}% beyond reference; maximum ${policy.maxChasePct.toFixed(2)}%.`)}evaluations++;localStorage.setItem('pai_evaluations',String(evaluations));renderDashboard();const eligible=!reasons.length,action=eligible?(direction==='long'?'BUY':'SELL'):'WAIT';$('decisionBox').className='decision '+(eligible?'good':'wait');$('decisionBox').querySelector('strong').textContent=action;$('decisionText').textContent=eligible?'Setup passes the configured local guardrails.':'Setup does not pass the configured guardrails.';$('rr').textContent=rr.toFixed(2);$('riskPct').textContent=riskPct.toFixed(3)+'%';$('chasePct').textContent=chase.toFixed(3)+'%';$('positionRisk').textContent=positionRisk.toFixed(2);$('reasons').innerHTML='';(eligible?['All configured local guardrails passed.','Automatic live orders use the separate backend agentic scanner.']:reasons).forEach(r=>{const li=document.createElement('li');li.textContent=r;$('reasons').appendChild(li)})}
function setValues(v){Object.entries(v).forEach(([k,val])=>$(k).value=val)}
function loadValid(){setValues({symbol:'RELIANCE',market:'NSE',direction:'long',currentPrice:101,referencePrice:100,entryPrice:101,stopLoss:99,targetPrice:105,quantity:10,portfolioValue:100000,quoteAge:0,sourceCount:2});['newsChecked','technicalChecked','portfolioChecked'].forEach(id=>$(id).checked=true);$('liveRequested').checked=false;evaluateTrade()}
function loadRejected(){setValues({symbol:'TEST',market:'NSE',direction:'long',currentPrice:104,referencePrice:100,entryPrice:104,stopLoss:99,targetPrice:108,quantity:500,portfolioValue:100000,quoteAge:180,sourceCount:1});$('newsChecked').checked=false;$('technicalChecked').checked=true;$('portfolioChecked').checked=true;$('liveRequested').checked=true;evaluateTrade()}

const brokers=['Groww'];$('brokerCards').innerHTML=brokers.map(b=>`<div class="broker"><div><b>${b}</b><div class="muted">Backend API integration</div></div><button class="secondary" onclick="showBrokerInfo('${b}')">Connection info</button></div>`).join('');
function showBrokerInfo(name){$('brokerInfo').innerHTML=`<b>${esc(name)}</b><br>Official broker API runs only in the backend. Secrets remain in backend/.env and are never stored in this page.`}
function loadSettings(){$('sRisk').value=policy.maxRiskPerTradePct;$('sRR').value=policy.minRewardRiskRatio;$('sChase').value=policy.maxChasePct;$('sQuoteAge').value=policy.maxPriceAgeSeconds;$('sSources').value=policy.minConfirmationSources}
function saveSettings(){policy.maxRiskPerTradePct=num('sRisk');policy.minRewardRiskRatio=num('sRR');policy.maxChasePct=num('sChase');policy.maxPriceAgeSeconds=num('sQuoteAge');policy.minConfirmationSources=num('sSources');localStorage.setItem('pai_policy',JSON.stringify(policy));alert('Local evaluator settings saved. Live scanner risk settings remain server-side in backend/.env.')}
function clearLocalData(){if(confirm('Clear all locally saved portfolio, settings, and skipped signals?')){localStorage.removeItem('pai_policy');localStorage.removeItem('pai_portfolio');localStorage.removeItem('pai_evaluations');sessionStorage.removeItem('pai_skipped_signals');location.reload()}}

async function hydrateLiveState(){try{const r=await fetch(`${backendHttp()}/api/live/state`);if(!r.ok)return;const s=await r.json();liveState={...liveState,...s};if(Array.isArray(s.opportunities))applyOpportunitySnapshot(s.opportunities,s.market_regime,s.scan_at);renderPortfolio();renderNews();renderRecommendations()}catch(_){}}
function handleLiveEvent(msg){
  liveState.lastEvent=msg.ts||new Date().toISOString();
  if(msg.type==='snapshot'){
    liveState.recommendations=msg.recommendations||liveState.recommendations;liveState.opportunities=msg.opportunities||Object.values(liveState.recommendations);liveState.holdings=msg.holdings||liveState.holdings;liveState.positions=msg.positions||liveState.positions;liveState.live_execution_enabled=Boolean(msg.live_execution_enabled);liveState.market_regime=msg.market_regime||liveState.market_regime;liveState.scan_at=msg.scan_at||liveState.scan_at;
  }else if(msg.type==='opportunities'){
    applyOpportunitySnapshot(msg.items||[],msg.market_regime,msg.scan_at);
  }else if(msg.type==='buy_alert'){
    showBuyAlert(msg.items||[]);
  }else if(msg.type==='portfolio'){
    liveState.holdings=msg.holdings||liveState.holdings;liveState.positions=msg.positions||liveState.positions;
  }else if(msg.type==='order'){
    liveState.orders.unshift(msg.data);
  }else if(msg.type==='news'){
    liveState.news=msg.items||[];
  }else if(msg.type==='scanner_error'){
    const status=$('liveStatus');if(status){status.className='warn';status.innerHTML=`<b>Scanner error</b><br>${esc(msg.message||'Unknown error')}`}
  }
  renderPortfolio();renderNews();renderRecommendations();renderOpportunityCount();
}
function connectLive(){clearTimeout(reconnectTimer);try{liveSocket=new WebSocket(backendWs());liveSocket.onopen=()=>{liveState.connected=true;renderLiveStatus();hydrateLiveState()};liveSocket.onmessage=e=>{try{handleLiveEvent(JSON.parse(e.data))}catch(_){}};liveSocket.onerror=()=>liveSocket.close();liveSocket.onclose=()=>{liveState.connected=false;renderLiveStatus();reconnectTimer=setTimeout(connectLive,1500)}}catch(_){reconnectTimer=setTimeout(connectLive,1500)}}

document.querySelectorAll('.nav button').forEach(btn=>btn.addEventListener('click',()=>{document.querySelectorAll('.nav button').forEach(b=>b.classList.remove('active'));document.querySelectorAll('.section').forEach(s=>s.classList.remove('active'));btn.classList.add('active');$(btn.dataset.section).classList.add('active')}));
window.addEventListener('click',e=>{if(e.target===$('buyAlertModal'))closeAlertModal()});
setInterval(()=>{renderRecommendations();renderOpportunityCount()},1000);
renderPortfolio();loadSettings();loadValid();renderNews();renderRecommendations();connectLive();
