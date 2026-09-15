from pathlib import Path
import re

root=Path.cwd(); j=root/'app/src/main/java/com/suhas/multyfideliverybuy'

def rw(path, fn):
    p=Path(path); s=p.read_text(); n=fn(s); p.write_text(n)

rw(root/'app/build.gradle', lambda s:s.replace('versionCode 146','versionCode 147').replace("versionName '1.4.6'","versionName '1.4.7'"))

p=j/'GrowwClient.java'; s=p.read_text()
s=s.replace('private static final String POSITION_SYMBOL_URL = "https://api.groww.in/v1/positions/trading-symbol";',
            'private static final String POSITION_SYMBOL_URL = "https://api.groww.in/v1/positions/trading-symbol";\n    private static final String HOLDINGS_URL = "https://api.groww.in/v1/holdings/user";')
start=s.index('    static PositionSnapshot getCncPosition(Context context, String symbol) {')
end=s.index('    /** Multyfi Intraday notification', start)
block=r'''    static int combinedDeliveryQuantity(int positionQty, int holdingQty, int dematFreeQty, int t1Qty) {
        return Math.max(Math.max(0, positionQty), Math.max(Math.max(0, holdingQty), Math.max(0, dematFreeQty) + Math.max(0, t1Qty)));
    }

    private static PositionSnapshot getRawCncPosition(Context context, String symbol) {
        try {
            String endpoint = POSITION_SYMBOL_URL + "?trading_symbol=" + URLEncoder.encode(symbol, StandardCharsets.UTF_8.name()) + "&segment=CASH";
            HttpResponse r = get(endpoint, ensureToken(context), true);
            if (r.code == 401 || r.code == 403) { AppPrefs.clearAccessToken(context); Result a=authenticate(context); if(!a.success)return new PositionSnapshot(false,-1,0,a.message); r=get(endpoint,AppPrefs.getAccessToken(context),true); }
            if (r.code >= 200 && r.code < 300) {
                JSONObject xj=new JSONObject(r.body); JSONObject payload=xj.optJSONObject("payload"); JSONArray arr=payload==null?null:payload.optJSONArray("positions");
                if(arr!=null) for(int i=0;i<arr.length();i++){ JSONObject x=arr.optJSONObject(i); if(x==null)continue; if(!symbol.equalsIgnoreCase(x.optString("trading_symbol",symbol)))continue; if(!"CNC".equalsIgnoreCase(x.optString("product","CNC")))continue; return new PositionSnapshot(true,x.optInt("quantity",0),x.optDouble("net_price",0),"Position API OK"); }
                return new PositionSnapshot(true,0,0,"Position API reports zero CNC quantity.");
            }
            return new PositionSnapshot(false,-1,0,"Position HTTP "+r.code+": "+shortText(r.body));
        } catch(Exception e){ return new PositionSnapshot(false,-1,0,safeMessage(e)); }
    }

    private static PositionSnapshot getCncHolding(Context context, String symbol) {
        try {
            HttpResponse r=get(HOLDINGS_URL,ensureToken(context),true);
            if(r.code==401||r.code==403){ AppPrefs.clearAccessToken(context); Result a=authenticate(context); if(!a.success)return new PositionSnapshot(false,-1,0,a.message); r=get(HOLDINGS_URL,AppPrefs.getAccessToken(context),true); }
            if(r.code>=200&&r.code<300){
                JSONObject xj=new JSONObject(r.body); JSONObject payload=xj.optJSONObject("payload"); JSONArray arr=payload==null?null:payload.optJSONArray("holdings");
                if(arr!=null) for(int i=0;i<arr.length();i++){ JSONObject x=arr.optJSONObject(i); if(x==null)continue; if(!symbol.equalsIgnoreCase(x.optString("trading_symbol","")))continue; int h=x.optInt("quantity",0); int f=(int)Math.floor(Math.max(0.0,x.optDouble("demat_free_quantity",0.0))+1e-9); int t=(int)Math.floor(Math.max(0.0,x.optDouble("t1_quantity",0.0))+1e-9); int q=combinedDeliveryQuantity(0,h,f,t); return new PositionSnapshot(true,q,x.optDouble("average_price",0),"Holdings API OK • holding="+h+" • dematFree="+f+" • T1="+t); }
                return new PositionSnapshot(true,0,0,"Holdings API reports no matching delivery holding/T1.");
            }
            return new PositionSnapshot(false,-1,0,"Holdings HTTP "+r.code+": "+shortText(r.body));
        } catch(Exception e){ return new PositionSnapshot(false,-1,0,safeMessage(e)); }
    }

    static PositionSnapshot getCncPosition(Context context, String symbol) {
        PositionSnapshot pos=getRawCncPosition(context,symbol), hold=getCncHolding(context,symbol);
        if(hold.success){ int pq=pos.success?pos.quantity:0; int q=Math.max(Math.max(0,pq),Math.max(0,hold.quantity)); double px=hold.netPrice>0?hold.netPrice:(pos.success?pos.netPrice:0); return new PositionSnapshot(true,q,px,"Delivery reconciliation • position="+Math.max(0,pq)+" • holding/T1="+Math.max(0,hold.quantity)+" • "+hold.message); }
        if(pos.success&&pos.quantity>0) return new PositionSnapshot(true,pos.quantity,pos.netPrice,"Delivery reconciliation used non-zero position because holdings lookup failed • "+hold.message);
        if(pos.success) return new PositionSnapshot(false,-1,pos.netPrice,"Position API reports zero, but holdings/T1 lookup failed; refusing to assume the delivery holding is gone. "+hold.message);
        return new PositionSnapshot(false,-1,0,"Both position and holdings/T1 reconciliation failed • position: "+pos.message+" • holdings: "+hold.message);
    }

    static int recoverTodayUnivestEntryQuantity(Context context, String symbol) {
        if(symbol==null||symbol.trim().isEmpty())return 0; String wanted=symbol.trim().toUpperCase(Locale.US);
        try { int qty=0; String latest=""; for(int page=0;page<5;page++){
            String endpoint=ORDER_LIST_URL+"?segment=CASH&page="+page+"&page_size=100"; HttpResponse r=get(endpoint,ensureToken(context),true);
            if(r.code==401||r.code==403){AppPrefs.clearAccessToken(context);Result a=authenticate(context);if(!a.success)return 0;r=get(endpoint,AppPrefs.getAccessToken(context),true);} if(!(r.code>=200&&r.code<300))return 0;
            JSONObject xj=new JSONObject(r.body);JSONObject payload=xj.optJSONObject("payload");JSONArray list=payload==null?null:payload.optJSONArray("order_list");if(list==null||list.length()==0)break;
            for(int i=0;i<list.length();i++){JSONObject o=list.optJSONObject(i);if(o==null)continue;if(!wanted.equalsIgnoreCase(o.optString("trading_symbol","")))continue;if(!"CNC".equalsIgnoreCase(o.optString("product","")))continue;if(!"BUY".equalsIgnoreCase(o.optString("transaction_type","")))continue;String ref=o.optString("order_reference_id","").toUpperCase(Locale.US);if(!ref.startsWith("UVE"))continue;int f=o.optInt("filled_quantity",0);if(f<=0)continue;String t=o.optString("exchange_time",o.optString("created_at",""));if(qty==0||t.compareTo(latest)>=0){qty=f;latest=t;}}
            if(list.length()<100)break;
        } return qty; } catch(Exception e){ return 0; }
    }

'''
s=s[:start]+block+s[end:]; p.write_text(s)

p=j/'UnivestManager.java'; s=p.read_text()
s=s.replace('''        UnivestStateStore.State state = UnivestStateStore.get(context, symbol);\n        if (state == null || UnivestStateStore.EXITED.equals(state.phase)) {\n            status(context, "UNIVEST EXIT RECEIVED • " + symbol + " • NO UNIVEST HOLDING — already sold/not tracked.");\n            return;\n        }\n''','''        UnivestStateStore.State state = UnivestStateStore.get(context, symbol);\n        if (state == null) { status(context, "UNIVEST EXIT RECEIVED • " + symbol + " • NO UNIVEST HOLDING — not tracked."); return; }\n        if (UnivestStateStore.EXITED.equals(state.phase)) {\n            if (isLegacyFalseZeroExit(state)) {\n                GrowwClient.PositionSnapshot d=GrowwClient.getCncPosition(context,symbol); int r=GrowwClient.recoverTodayUnivestEntryQuantity(context,symbol); int q=d.success?Math.min(Math.max(0,d.quantity),Math.max(0,r)):0;\n                if(q>0){ state.phase=UnivestStateStore.ACTIVE; state.quantity=q; state.principal=state.anchorPrice>0?state.anchorPrice*q:0; state.estimatedBuyCharges=state.principal>0?DeliveryNetTarget.buyCharges(state.principal):0; state.brokerQtyAfterLastFill=d.quantity; state.lastAction="v1.4.7 recovered v1.4.6 false zero-holding exit; official exit will retry."; UnivestStateStore.put(context,state); }\n                else { status(context,"UNIVEST EXIT RECEIVED • "+symbol+" • prior cycle is EXITED; legacy recovery found no provable remaining app-owned quantity."); return; }\n            } else { status(context, "UNIVEST EXIT RECEIVED • " + symbol + " • NO UNIVEST HOLDING — already sold/not tracked."); return; }\n        }\n''')

old='''        int sellQty = Math.min(state.quantity, Math.max(0, broker.quantity));\n        if (sellQty <= 0) {\n            state.phase = UnivestStateStore.EXITED;\n            state.quantity = 0;\n            state.principal = 0;\n            state.estimatedBuyCharges = 0;\n            state.exitOrderId = "";\n            state.exitRequestedQty = 0;\n            state.brokerQtyAfterLastFill = broker.quantity;\n            state.lastAction = "Official Univest exit received; no remaining CNC quantity after sell-order reconciliation.";\n            UnivestStateStore.put(context, state);\n            status(context, "UNIVEST OFFICIAL EXIT COMPLETE • " + symbol + " • NO HOLDING remained after reconciliation • " + cleanup.message);\n            return;\n        }\n'''
new='''        int sellQty = Math.min(state.quantity, Math.max(0, broker.quantity));\n        if (sellQty <= 0) {\n            state.phase=UnivestStateStore.ERROR; state.exitOrderId=""; state.exitRequestedQty=0; state.brokerQtyAfterLastFill=broker.quantity;\n            state.lastAction="Official exit reconciliation returned zero while app still tracks qty "+state.quantity+"; state preserved and NOT marked exited. "+broker.message; UnivestStateStore.put(context,state);\n            status(context,"UNIVEST EXIT RECONCILIATION PENDING • "+symbol+" • app still tracks qty "+state.quantity+" • position+holdings/T1 shows zero • NOT marked exited."); return;\n        }\n'''
if old not in s: raise SystemExit('official zero branch not found')
s=s.replace(old,new)

old='''        int sellQty = Math.min(state.quantity, Math.max(0, broker.quantity));\n        if (sellQty <= 0) {\n            state.phase = UnivestStateStore.FLAT_WAIT_EXIT;\n            state.quantity = 0;\n            state.principal = 0;\n            state.estimatedBuyCharges = 0;\n            state.exitOrderId = "";\n            state.exitRequestedQty = 0;\n            state.brokerQtyAfterLastFill = broker.quantity;\n            state.lastAction = "Profit capture found no remaining CNC holding after sell-order reconciliation; staying flat until Univest official exit.";\n            UnivestStateStore.put(context, state);\n            status(context, "UNIVEST PROFIT CAPTURE • " + state.symbol + " • NO HOLDING remained after reconciliation • staying flat until official exit.");\n            return;\n        }\n'''
new='''        int sellQty = Math.min(state.quantity, Math.max(0, broker.quantity));\n        if (sellQty <= 0) {\n            state.phase=UnivestStateStore.ERROR; state.exitOrderId=""; state.exitRequestedQty=0; state.brokerQtyAfterLastFill=broker.quantity;\n            state.lastAction="Profit capture reconciliation returned zero while app still tracks qty "+state.quantity+"; state preserved and NOT flattened. "+broker.message; UnivestStateStore.put(context,state);\n            status(context,"UNIVEST ₹2,500 NET CAPTURE RECONCILIATION PENDING • "+state.symbol+" • tracked qty "+state.quantity+" preserved."); return;\n        }\n'''
if old not in s: raise SystemExit('profit zero branch not found')
s=s.replace(old,new)

s=s.replace('''        for (UnivestStateStore.State state : states) {\n            try {\n                if (UnivestStateStore.EXITED.equals(state.phase) || UnivestStateStore.ERROR.equals(state.phase)) continue;\n''','''        for (UnivestStateStore.State state : states) {\n            try {\n                if (UnivestStateStore.EXITED.equals(state.phase)) { if(isLegacyFalseZeroExit(state)) handleExit(context,new UnivestParser.Signal(UnivestParser.Type.EXIT,state.symbol,"v1.4.7 legacy false-zero recovery"),System.currentTimeMillis()); continue; }\n                if (UnivestStateStore.ERROR.equals(state.phase)) continue;\n''')
marker='    private static GrowwClient.Result cancelTrackedGttSafe(Context context, UnivestStateStore.State state) {'
s=s.replace(marker,'    static boolean isLegacyFalseZeroExit(UnivestStateStore.State state) { if(state==null||!UnivestStateStore.EXITED.equals(state.phase))return false; String a=state.lastAction==null?"":state.lastAction; return a.contains("no remaining CNC quantity after sell-order reconciliation"); }\n\n'+marker)
p.write_text(s)

rw(j/'MainActivity.java',lambda s:s.replace('v1.4.6  •  DELIVERY FIRST','v1.4.7  •  DELIVERY FIRST').replace('v1.4.6 • Delivery Trade Hub','v1.4.7 • Delivery Trade Hub'))

p=root/'app/src/test/java/com/suhas/multyfideliverybuy/UnivestStrategyContractTest.java'; s=p.read_text(); i=s.rfind('}')
s=s[:i]+'''\n    @org.junit.Test public void deliveryReconciliationUsesHoldingsAndT1WhenPositionIsZero(){ org.junit.Assert.assertEquals(194,GrowwClient.combinedDeliveryQuantity(0,194,194,0)); org.junit.Assert.assertEquals(194,GrowwClient.combinedDeliveryQuantity(0,0,0,194)); org.junit.Assert.assertEquals(194,GrowwClient.combinedDeliveryQuantity(194,0,0,0)); }\n    @org.junit.Test public void legacyFalseZeroExitIsRecognizedNarrowly(){ UnivestStateStore.State x=new UnivestStateStore.State(); x.phase=UnivestStateStore.EXITED; x.lastAction="Official Univest exit received; no remaining CNC quantity after sell-order reconciliation."; org.junit.Assert.assertTrue(UnivestManager.isLegacyFalseZeroExit(x)); x.lastAction="normal"; org.junit.Assert.assertFalse(UnivestManager.isLegacyFalseZeroExit(x)); }\n'''+s[i:]; p.write_text(s)

p=root/'scripts/validate_contract.py'; s=p.read_text().replace("'version 1.4.6':\"versionName '1.4.6'\" in gradle and 'versionCode 146' in gradle,","'version 1.4.7':\"versionName '1.4.7'\" in gradle and 'versionCode 147' in gradle,")
needle=" 'Univest regular sell conflict reconciliation':'/v1/order/list' in groww and '/v1/order/cancel' in groww and 'cancelOpenCncSellOrdersForSymbol' in groww and 'shouldCancelCncSellOrder' in groww and 'Math.min(state.quantity, Math.max(0, broker.quantity))' in univest,"
s=s.replace(needle,needle+"\n 'Univest holdings T1 reconciliation':'/v1/holdings/user' in groww and 'demat_free_quantity' in groww and 't1_quantity' in groww and 'combinedDeliveryQuantity' in groww,\n 'Univest zero snapshot preserves state':'UNIVEST EXIT RECONCILIATION PENDING' in univest and 'state preserved and NOT marked exited' in univest,\n 'Univest v146 false exit recovery':'recoverTodayUnivestEntryQuantity' in groww and 'isLegacyFalseZeroExit' in univest and 'v1.4.7 legacy false-zero recovery' in univest,")
p.write_text(s)

p=root/'README.md'; s=p.read_text()+'''\n\n## v1.4.7 — Univest holdings/T1 exit fix\n- Fixes the PDMJEPAPER case where v1.4.6 saw zero in Positions, falsely reported NO HOLDING, and sent no sell order despite 194 CNC shares remaining.\n- Univest now reconciles Groww Positions + Holdings + demat_free_quantity + t1_quantity before CNC exit sizing.\n- A zero Position alone can no longer mark a tracked strategy EXITED; tracked quantity is preserved when reconciliation is ambiguous.\n- Narrow recovery for the exact v1.4.6 false-zero state uses today's app UVE BUY history plus current holdings/T1 to retry the already-received official exit.\n- Existing Univest and Multyfi rules are unchanged.\n'''; p.write_text(s)
print('Applied v1.4.7 holdings/T1 exit fix')
