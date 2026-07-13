const DEFAULT_POLICY={enabled:true,allowLiveExecution:false,maxRiskPerTradePct:1,minRewardRiskRatio:2,maxChasePct:1.5,maxPriceAgeSeconds:120,minConfirmationSources:2};
let policy=JSON.parse(localStorage.getItem('pai_policy')||'null')||{...DEFAULT_POLICY};
let portfolio=JSON.parse(localStorage.getItem('pai_portfolio')||'[]');
let evaluations=Number(localStorage.getItem('pai_evaluations')||'0');
let liveState={connected:false,lastEvent:null,prices:{},news:[],holdings:[],positions:[],orders:[],recommendations:{},live_execution_enabled:false};
let liveSocket=null,reconnectTimer=null;

const $=id=>document.getElementById(id),num=id=>Number($(id).value),checked=id=>$(id).checked;
const money=n=>new Intl.NumberFormat('en-IN',{style:'currency',currency:'INR',maximumFractionDigits:2}).format(n||0);
const backendHttp=()=>`${location.protocol==='https:'?'https':'http'}://${location.hostname||'127.0.0.1'}:8000`;
const backendWs=()=>`${location.protocol==='https:'?'wss':'ws'}://${location.hostname||'127.0.0.1'}:8000/ws/live`;
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]));

document.querySelectorAll('.nav button').forEach(btn=>btn.addEventListener('click',()=>{document.querySelectorAll('.nav button').forEach(b=>b.classList.remove('active'));document.querySelectorAll('.section').forEach(s=>s.classList.remove('active'));btn.classList.add('active');$(btn.dataset.section).classList.add('active')}));

function latestPrice(symbol){const key=Object.keys(liveState.prices).find(k=>k.endsWith(`:${symbol}`)||k===symbol);const event=key?liveState.prices[key]:null;return event?.ltp??event?.price??event?.last_price??null}

function renderDashboard(){
  const source=liveState.holdings.length?liveState.holdings:portfolio;
  const value=source.reduce((s,p)=>{const symbol=p.trading_symbol||p.symbol||p.tradingsymbol||'';const qty=Number(p.quantity??p.qty??0);const avg=Number(p.average_price??p.avg??p.averagePrice??0);const lp=latestPrice(symbol);return s+qty*(Number(lp)||avg)},0);
  $('kpiPortfolio').textContent=money(value);
  $('kpiPositions').textContent=(liveState.positions.length||source.length);
  $('kpiEvaluations').textContent=evaluations;
  const execution=$('liveExecutionStatus');
  if(execution){execution.textContent=liveState.live_execution_enabled?'ON':'OFF';execution.className=liveState.live_execution_enabled?'':'off'}
  $('dashboardPositions').innerHTML=source.length?source.slice(-8).reverse().map(p=>{const symbol=p.trading_symbol||p.symbol||p.tradingsymbol||'';const market=p.exchange||p.market||'NSE';const qty=Number(p.quantity??p.qty??0);const avg=Number(p.average_price??p.avg??p.averagePrice??0);const lp=latestPrice(symbol);return `<tr><td>${esc(symbol)}</td><td>${esc(market)}</td><td>${qty}</td><td>${avg||'—'}</td><td>${lp?money(qty*lp):money(qty*avg)}</td></tr>`}).join(''):'<tr><td colspan="5" class="muted">No positions saved.</td></tr>';
  renderLiveStatus();
  renderRecommendations();
}

function renderPortfolio(){$('portfolioRows').innerHTML=portfolio.length?portfolio.map((p,i)=>`<tr><td>${esc(p.symbol)}</td><td>${esc(p.market)}</td><td>${p.qty}</td><td>${p.avg}</td><td>${money(p.qty*(latestPrice(p.symbol)||p.avg))}</td><td><button class="secondary" onclick="removePosition(${i})">Remove</button></td></tr>`).join(''):'<tr><td colspan="6" class="muted">No positions saved.</td></tr>';renderDashboard()}

function renderLiveStatus(){const status=$('liveStatus');if(!status)return;status.className=liveState.connected?'safe':'warn';status.innerHTML=`<b>${liveState.connected?'Backend stream connected':'Backend stream disconnected'}</b><br>${liveState.lastEvent?`Last event: ${new Date(liveState.lastEvent).toLocaleTimeString()}`:'Waiting for backend events.'}`}

function renderNews(){const box=$('liveNews');if(!box)return;box.innerHTML=liveState.news.length?liveState.news.slice(0,12).map(n=>`<div class="broker"><div><b>${esc(n.title||'Headline')}</b><div class="muted">${esc(n.source||'')}${n.published?` · ${esc(n.published)}`:''}</div></div></div>`).join(''):'<div class="muted">News integration is separate from Groww market execution.</div>'}

function renderRecommendations(){
  const board=$('recommendationBoard');if(!board)return;
  const items=Object.values(liveState.recommendations||{}).sort((a,b)=>(b.action==='BUY')-(a.action==='BUY')||Number(b.score||0)-Number(a.score||0));
  if(!items.length){board.innerHTML='<div class="muted">Waiting for live recommendations.</div>';return}
  board.innerHTML=items.map(r=>{
    const isBuy=r.action==='BUY';
    const canExecute=isBuy&&liveState.live_execution_enabled;
    const reason=(r.reasons||[]).slice(0,3).map(esc).join(' · ');
    return `<div class="broker">
      <div style="flex:1">
        <b>${esc(r.symbol)} · ${esc(r.exchange)} · ${esc(r.action)}</b>
        <div class="muted">Entry ${money(r.entry_price)} · Target ${money(r.target_price)} · Stop ${money(r.stop_loss)} · Qty ${Number(r.quantity||0)} · Score ${Number(r.score||0)}</div>
        <div class="muted">${reason}</div>
      </div>
      ${isBuy?`<button ${canExecute?'':'disabled'} onclick="buyRecommendation('${esc(r.recommendation_id)}')">${canExecute?'BUY NOW':'LIVE OFF'}</button>`:'<button class="secondary" disabled>WAIT</button>'}
    </div>`
  }).join('');
}

async function buyRecommendation(recommendationId){
  const rec=Object.values(liveState.recommendations).find(r=>r.recommendation_id===recommendationId);
  if(!rec){alert('This recommendation is no longer available. Wait for the next refresh.');return}
  const message=`Send REAL Groww BUY order?\n\n${rec.symbol} (${rec.exchange})\nEntry: ${rec.entry_price}\nTarget: ${rec.target_price}\nStop loss: ${rec.stop_loss}\nQuantity: ${rec.quantity}\n\nThe backend will re-check the live quote before submitting.`;
  if(!confirm(message))return;
  try{
    const response=await fetch(`${backendHttp()}/api/orders/buy-recommendation`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({recommendation_id:recommendationId})});
    const data=await response.json();
    if(!response.ok)throw new Error(data.detail||'Order was blocked.');
    const order=data.order||{};
    alert(`Groww order submitted.\nOrder ID: ${order.groww_order_id||'See broker response'}\nStatus: ${order.order_status||'Submitted'}`);
  }catch(err){alert(`Order not submitted: ${err.message}`)}
}

function addPosition(){const p={symbol:$('pSymbol').value.trim().toUpperCase(),market:$('pMarket').value,qty:num('pQty'),avg:num('pAvg')};if(!p.symbol||!(p.qty>0)||!(p.avg>0)){alert('Enter a valid symbol, quantity and average price.');return}portfolio.push(p);localStorage.setItem('pai_portfolio',JSON.stringify(portfolio));$('pSymbol').value='';$('pQty').value='';$('pAvg').value='';renderPortfolio()}
function removePosition(i){portfolio.splice(i,1);localStorage.setItem('pai_portfolio',JSON.stringify(portfolio));renderPortfolio()}

function evaluateTrade(){const direction=$('direction').value,current=num('currentPrice'),reference=num('referencePrice'),entry=num('entryPrice'),stop=num('stopLoss'),target=num('targetPrice'),qty=num('quantity'),capital=num('portfolioValue'),quoteAge=num('quoteAge'),sources=num('sourceCount');const reasons=[];if(!$('symbol').value.trim())reasons.push('Symbol is required.');if(quoteAge>policy.maxPriceAgeSeconds)reasons.push(`Quote is stale (${quoteAge}s; maximum ${policy.maxPriceAgeSeconds}s).`);if(sources<policy.minConfirmationSources)reasons.push(`Insufficient confirmation sources (${sources}; minimum ${policy.minConfirmationSources}).`);const missing=[];if(!checked('newsChecked'))missing.push('news');if(!checked('technicalChecked'))missing.push('technical');if(!checked('portfolioChecked'))missing.push('portfolio');if(missing.length)reasons.push('Missing confirmations: '+missing.join(', ')+'.');let risk=0,reward=0;if(direction==='long'){if(!(stop<entry&&entry<target))reasons.push('Long setup must satisfy stop loss < entry < target.');risk=entry-stop;reward=target-entry}else{if(!(target<entry&&entry<stop))reasons.push('Short setup must satisfy target < entry < stop loss.');risk=stop-entry;reward=entry-target}const rr=risk>0&&reward>0?reward/risk:0;if(rr<policy.minRewardRiskRatio)reasons.push(`Reward/risk ${rr.toFixed(2)} is below minimum ${policy.minRewardRiskRatio.toFixed(2)}.`);const positionRisk=Math.max(0,risk)*Math.max(0,qty);const riskPct=capital>0?positionRisk/capital*100:0;if(riskPct>policy.maxRiskPerTradePct)reasons.push(`Position risks ${riskPct.toFixed(2)}% of portfolio; maximum ${policy.maxRiskPerTradePct.toFixed(2)}%.`);let chase=0;if(reference>0){chase=direction==='long'?(current-reference)/reference*100:(reference-current)/reference*100;if(chase>policy.maxChasePct)reasons.push(`Do not chase: ${chase.toFixed(2)}% beyond reference; maximum ${policy.maxChasePct.toFixed(2)}%.`)}evaluations++;localStorage.setItem('pai_evaluations',String(evaluations));renderDashboard();const eligible=!reasons.length,action=eligible?(direction==='long'?'BUY':'SELL'):'WAIT';$('decisionBox').className='decision '+(eligible?'good':'wait');$('decisionBox').querySelector('strong').textContent=action;$('decisionText').textContent=eligible?'Setup passes the configured local guardrails.':'Setup does not pass the configured guardrails.';$('rr').textContent=rr.toFixed(2);$('riskPct').textContent=riskPct.toFixed(3)+'%';$('chasePct').textContent=chase.toFixed(3)+'%';$('positionRisk').textContent=positionRisk.toFixed(2);$('reasons').innerHTML='';(eligible?['All configured local guardrails passed.','Automatic live orders use the separate backend recommendation engine.']:reasons).forEach(r=>{const li=document.createElement('li');li.textContent=r;$('reasons').appendChild(li)})}
function setValues(v){Object.entries(v).forEach(([k,val])=>$(k).value=val)}
function loadValid(){setValues({symbol:'RELIANCE',market:'NSE',direction:'long',currentPrice:101,referencePrice:100,entryPrice:101,stopLoss:99,targetPrice:105,quantity:10,portfolioValue:100000,quoteAge:0,sourceCount:2});['newsChecked','technicalChecked','portfolioChecked'].forEach(id=>$(id).checked=true);$('liveRequested').checked=false;evaluateTrade()}
function loadRejected(){setValues({symbol:'TEST',market:'NSE',direction:'long',currentPrice:104,referencePrice:100,entryPrice:104,stopLoss:99,targetPrice:108,quantity:500,portfolioValue:100000,quoteAge:180,sourceCount:1});$('newsChecked').checked=false;$('technicalChecked').checked=true;$('portfolioChecked').checked=true;$('liveRequested').checked=true;evaluateTrade()}

const brokers=['Groww','Zerodha / Kite','Interactive Brokers','Other broker'];$('brokerCards').innerHTML=brokers.map(b=>`<div class="broker"><div><b>${b}</b><div class="muted">${b==='Groww'?'Backend integration prepared':'Not connected'}</div></div><button class="secondary" onclick="showBrokerInfo('${b.replaceAll("'","\\'")}')">Connection info</button></div>`).join('');
function showBrokerInfo(name){$('brokerInfo').innerHTML=`<b>${esc(name)}</b><br>Use only the broker's official API. Secrets remain in backend/.env and are never stored in this page.`}
function loadSettings(){$('sRisk').value=policy.maxRiskPerTradePct;$('sRR').value=policy.minRewardRiskRatio;$('sChase').value=policy.maxChasePct;$('sQuoteAge').value=policy.maxPriceAgeSeconds;$('sSources').value=policy.minConfirmationSources}
function saveSettings(){policy.maxRiskPerTradePct=num('sRisk');policy.minRewardRiskRatio=num('sRR');policy.maxChasePct=num('sChase');policy.maxPriceAgeSeconds=num('sQuoteAge');policy.minConfirmationSources=num('sSources');localStorage.setItem('pai_policy',JSON.stringify(policy));alert('Settings saved locally in this browser. Backend live-order policy remains controlled by backend/.env.')}
function clearLocalData(){if(confirm('Clear all locally saved portfolio and settings data?')){localStorage.removeItem('pai_policy');localStorage.removeItem('pai_portfolio');localStorage.removeItem('pai_evaluations');location.reload()}}

async function hydrateLiveState(){try{const r=await fetch(`${backendHttp()}/api/live/state`);if(!r.ok)return;const s=await r.json();liveState={...liveState,...s};renderPortfolio();renderNews();renderRecommendations()}catch(_){}}
function handleLiveEvent(msg){
  liveState.lastEvent=msg.ts||new Date().toISOString();
  if(msg.type==='snapshot'){
    liveState.recommendations=msg.recommendations||liveState.recommendations;
    liveState.holdings=msg.holdings||liveState.holdings;
    liveState.positions=msg.positions||liveState.positions;
    liveState.live_execution_enabled=Boolean(msg.live_execution_enabled);
  }else if(msg.type==='recommendation'){
    const r=msg.data||{};if(r.symbol)liveState.recommendations[`${r.exchange||'NSE'}:${r.symbol}`]=r;
  }else if(msg.type==='portfolio'){
    liveState.holdings=msg.holdings||liveState.holdings;liveState.positions=msg.positions||liveState.positions;
  }else if(msg.type==='order'){
    liveState.orders.unshift(msg.data);
  }else if(msg.type==='news'){
    liveState.news=msg.items||[];
  }
  renderPortfolio();renderNews();renderRecommendations();
}
function connectLive(){clearTimeout(reconnectTimer);try{liveSocket=new WebSocket(backendWs());liveSocket.onopen=()=>{liveState.connected=true;renderLiveStatus();hydrateLiveState()};liveSocket.onmessage=e=>{try{handleLiveEvent(JSON.parse(e.data))}catch(_){}};liveSocket.onerror=()=>liveSocket.close();liveSocket.onclose=()=>{liveState.connected=false;renderLiveStatus();reconnectTimer=setTimeout(connectLive,1500)}}catch(_){reconnectTimer=setTimeout(connectLive,1500)}}

renderPortfolio();loadSettings();loadValid();renderNews();renderRecommendations();connectLive();
