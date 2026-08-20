package com.suhas.research360engine;

import android.content.Context;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;

/** Dependency-free Groww REST client with an in-process request throttle. */
public final class GrowwClient {
    private static final String ROOT="https://api.groww.in/v1";
    public static final String INSTRUMENT_CSV_URL="https://growwapi-assets.groww.in/instruments/instrument.csv";
    private static final Object RATE_LOCK=new Object();private static long lastApiRequest=0;
    private final SecureStore secure;private final Context context;private final Object tokenLock=new Object();private volatile String accessToken="";private volatile long tokenIssuedAt=0;
    public GrowwClient(Context c){context=c.getApplicationContext();secure=new SecureStore(c);}

    public boolean hasCredentials(){return !secure.get("api_key").trim().isEmpty()&&!secure.get("totp_secret").trim().isEmpty();}
    public void clearToken(){synchronized(tokenLock){accessToken="";tokenIssuedAt=0;}}
    public String ensureToken() throws Exception{
        synchronized(tokenLock){
            if(!accessToken.isEmpty()&&System.currentTimeMillis()-tokenIssuedAt<4L*60L*60L*1000L)return accessToken;
            return requestFreshTokenLocked();
        }
    }
    public String forceRefreshToken() throws Exception{synchronized(tokenLock){accessToken="";tokenIssuedAt=0;return requestFreshTokenLocked();}}
    private String requestFreshTokenLocked() throws Exception{
        String apiKey=secure.get("api_key").trim(),secret=secure.get("totp_secret").replace(" ","").trim();
        if(apiKey.isEmpty()||secret.isEmpty())throw new IllegalStateException("Groww TOTP token / TOTP secret not configured");
        JSONObject b=new JSONObject();b.put("key_type","totp");b.put("totp",totp(secret,System.currentTimeMillis()));
        HttpResult r=raw("POST",ROOT+"/token/api/access",b.toString(),apiKey,false,false);
        if(r.code<200||r.code>=300)throw new IllegalStateException("Groww authentication HTTP "+r.code+": "+safeMsg(r.body));
        JSONObject root=new JSONObject(r.body),payload=root.optJSONObject("payload");String token=root.optString("token","");if(token.isEmpty()&&payload!=null)token=payload.optString("token","");
        if(token.isEmpty())throw new IllegalStateException("Groww access token missing in authentication response");
        accessToken=token;tokenIssuedAt=System.currentTimeMillis();AppState.setApiAuthAt(context,tokenIssuedAt);return token;
    }
    public Health validate(boolean forceRefresh)throws Exception{
        Health h=new Health();try{
            if(forceRefresh)forceRefreshToken();else ensureToken();
            JSONObject u=authed("GET",ROOT+"/user/detail",null,true),p=u.optJSONObject("payload");if(p==null)p=u;
            h.ucc=p.optString("ucc","");h.nse=p.optBoolean("nse_enabled",false);JSONArray seg=p.optJSONArray("active_segments");h.cash=false;if(seg!=null)for(int i=0;i<seg.length();i++)if("CASH".equalsIgnoreCase(seg.optString(i)))h.cash=true;
            JSONObject pos=authed("GET",ROOT+"/positions/user?segment=CASH",null,true);boolean positionOk=!"FAILURE".equalsIgnoreCase(pos.optString("status",""));
            JSONObject q=authed("GET",ROOT+"/live-data/quote?exchange=NSE&segment=CASH&trading_symbol=RELIANCE",null,true);JSONObject qp=q.optJSONObject("payload");h.marketData=qp!=null&&(qp.optDouble("last_price",0)>0||qp.optDouble("close",0)>0||qp.length()>0);
            h.ok=h.nse&&h.cash&&positionOk&&h.marketData;h.message=h.ok?"Authenticated • NSE CASH + paid live data validated":"Validation incomplete: NSE="+h.nse+" CASH="+h.cash+" marketData="+h.marketData;
            AppState.setApiHealth(context,h.ok,h.message,h.ucc);return h;
        }catch(Exception e){h.ok=false;h.message=e.getMessage()==null?e.getClass().getSimpleName():e.getMessage();AppState.setApiHealth(context,false,h.message,h.ucc);throw e;}
    }
    public boolean testConnection()throws Exception{return validate(false).ok;}

    public Map<String,Double> getLtps(List<String> symbols)throws Exception{
        HashMap<String,Double> out=new HashMap<>();ArrayList<String> unique=clean(symbols);for(int start=0;start<unique.size();start+=50){int end=Math.min(start+50,unique.size());String joined=join(unique,start,end);JSONObject r=authed("GET",ROOT+"/live-data/ltp?segment=CASH&exchange_symbols="+enc(joined),null,true);JSONObject p=r.optJSONObject("payload");if(p!=null)for(int i=start;i<end;i++){String s=unique.get(i);double v=p.optDouble("NSE_"+s,Double.NaN);if(!Double.isNaN(v)&&v>0)out.put(s,v);}}return out;
    }
    public Map<String,Ohlc> getOhlc(List<String> symbols)throws Exception{
        HashMap<String,Ohlc> out=new HashMap<>();ArrayList<String> unique=clean(symbols);for(int start=0;start<unique.size();start+=50){int end=Math.min(start+50,unique.size());String joined=join(unique,start,end);JSONObject r=authed("GET",ROOT+"/live-data/ohlc?segment=CASH&exchange_symbols="+enc(joined),null,true);JSONObject p=r.optJSONObject("payload");if(p!=null)for(int i=start;i<end;i++){String s=unique.get(i);Object raw=p.opt("NSE_"+s);Ohlc o=parseOhlcValue(raw);if(o!=null)out.put(s,o);}}return out;
    }

    public Db.MarketSnapshot getQuote(String symbol)throws Exception{
        JSONObject r=authed("GET",ROOT+"/live-data/quote?exchange=NSE&segment=CASH&trading_symbol="+enc(symbol),null,true);JSONObject p=r.optJSONObject("payload");if(p==null)throw new IllegalStateException("Quote payload missing for "+symbol);Db.MarketSnapshot q=new Db.MarketSnapshot();q.ts=System.currentTimeMillis();q.ltp=p.optDouble("last_price",0);q.averagePrice=p.optDouble("average_price",0);q.bid=p.optDouble("bid_price",0);q.ask=p.optDouble("offer_price",0);q.totalBuy=p.optDouble("total_buy_quantity",0);q.totalSell=p.optDouble("total_sell_quantity",0);q.volume=p.optDouble("volume",0);q.dayChangePct=p.has("day_change_perc")?p.optDouble("day_change_perc",0):p.optDouble("day_change_percentage",0);q.marketCap=p.optDouble("market_cap",0);q.lastTradeQty=p.optDouble("last_trade_quantity",0);q.week52High=p.optDouble("week_52_high",0);q.week52Low=p.optDouble("week_52_low",0);parseOhlc(p.opt("ohlc"),q);if(q.dayHigh<=0)q.dayHigh=Math.max(q.ltp,p.optDouble("high_trade_range",q.ltp));if(q.dayLow<=0)q.dayLow=Math.min(q.ltp,p.optDouble("low_trade_range",q.ltp));if(q.bid<=0||q.ask<=0)parseTopDepth(p.optJSONObject("depth"),q);q.depthImbalance=depthImbalance(p.optJSONObject("depth"));if(q.depthImbalance==0&&q.totalBuy+q.totalSell>0)q.depthImbalance=(q.totalBuy-q.totalSell)/(q.totalBuy+q.totalSell);double mid=(q.bid>0&&q.ask>0)?(q.bid+q.ask)/2:q.ltp;q.spreadBps=(mid>0&&q.ask>=q.bid&&q.bid>0)?((q.ask-q.bid)/mid)*10000:0;q.rangePosition=(q.dayHigh>q.dayLow&&q.ltp>0)?clamp((q.ltp-q.dayLow)/(q.dayHigh-q.dayLow),0,1):.5;return q;
    }

    public List<Candle> historical5m(String symbol,String start,String end)throws Exception{
        String u=ROOT+"/historical/candles?exchange=NSE&segment=CASH&groww_symbol="+enc("NSE-"+symbol)+"&start_time="+enc(start)+"&end_time="+enc(end)+"&candle_interval=5minute";JSONObject r=authed("GET",u,null,true);JSONObject p=r.optJSONObject("payload");JSONArray a=p==null?null:p.optJSONArray("candles");ArrayList<Candle> out=new ArrayList<>();if(a==null)return out;for(int i=0;i<a.length();i++){JSONArray x=a.optJSONArray(i);if(x==null||x.length()<6)continue;Candle c=new Candle();c.open=x.optDouble(1,0);c.high=x.optDouble(2,0);c.low=x.optDouble(3,0);c.close=x.optDouble(4,0);c.volume=x.optDouble(5,0);out.add(c);}return out;
    }

    public String downloadInstrumentCsv()throws Exception{HttpResult r=raw("GET",INSTRUMENT_CSV_URL,null,"",false,true);if(r.code<200||r.code>=300)throw new IllegalStateException("Instrument CSV HTTP "+r.code);return r.body;}
    public String fetchPublicText(String url)throws Exception{HttpResult r=raw("GET",url,null,"",false,true);if(r.code<200||r.code>=300)throw new IllegalStateException("Public HTTP "+r.code);return r.body;}

    public OrderResult placeMarket(String symbol,int qty,String product,String side)throws Exception{return placeOrder(symbol,qty,product,side,"MARKET",0);}
    public OrderResult placeLimit(String symbol,int qty,String product,String side,double price)throws Exception{if(price<=0)throw new IllegalArgumentException("limit price <= 0");return placeOrder(symbol,qty,product,side,"LIMIT",price);}
    private OrderResult placeOrder(String symbol,int qty,String product,String side,String type,double price)throws Exception{if(qty<=0)throw new IllegalArgumentException("quantity <= 0");JSONObject b=new JSONObject();b.put("trading_symbol",symbol);b.put("quantity",qty);if(price>0)b.put("price",round2(price));b.put("validity","DAY");b.put("exchange","NSE");b.put("segment","CASH");b.put("product",product);b.put("order_type",type);b.put("transaction_type",side);b.put("order_reference_id",reference(side));JSONObject r=authed("POST",ROOT+"/order/create",b.toString(),false);JSONObject p=r.optJSONObject("payload");if(p==null)throw new IllegalStateException("Groww order response missing payload: "+r);OrderResult o=new OrderResult();o.orderId=p.optString("groww_order_id","");o.status=p.optString("order_status","");o.remark=p.optString("remark","");if(o.orderId.isEmpty())throw new IllegalStateException("Groww order id missing: "+safeMsg(r.toString()));return o;}
    public void cancelOrder(String orderId)throws Exception{if(orderId==null||orderId.isEmpty())return;JSONObject b=new JSONObject();b.put("segment","CASH");b.put("groww_order_id",orderId);authed("POST",ROOT+"/order/cancel",b.toString(),false);}
    public OrderDetail getOrderDetail(String orderId)throws Exception{JSONObject r=authed("GET",ROOT+"/order/detail/"+enc(orderId)+"?segment=CASH",null,true);JSONObject p=r.optJSONObject("payload");if(p==null)throw new IllegalStateException("Order detail payload missing");OrderDetail d=new OrderDetail();d.orderId=p.optString("groww_order_id",orderId);d.status=p.optString("order_status","");d.filledQty=p.optInt("filled_quantity",0);d.quantity=p.optInt("quantity",0);d.remainingQty=p.has("remaining_quantity")?p.optInt("remaining_quantity",0):Math.max(0,d.quantity-d.filledQty);d.averageFillPrice=p.optDouble("average_fill_price",0);return d;}
    public SmartOrderResult placeGttSell(String symbol,int qty,String product,double targetPrice)throws Exception{if(qty<=0||targetPrice<=0)throw new IllegalArgumentException("Invalid GTT quantity/target");JSONObject child=new JSONObject();child.put("order_type","LIMIT");child.put("price",round2(targetPrice));child.put("transaction_type","SELL");JSONObject b=new JSONObject();b.put("reference_id",smartReference());b.put("smart_order_type","GTT");b.put("segment","CASH");b.put("trading_symbol",symbol);b.put("quantity",qty);b.put("trigger_price",String.format(Locale.US,"%.2f",targetPrice));b.put("trigger_direction","UP");b.put("order",child);b.put("product_type",product);b.put("exchange","NSE");b.put("duration","DAY");JSONObject r=authed("POST",ROOT+"/order-advance/create",b.toString(),false);JSONObject p=r.optJSONObject("payload");if(p==null)throw new IllegalStateException("GTT response missing payload");SmartOrderResult x=new SmartOrderResult();x.smartOrderId=p.optString("smart_order_id","");x.status=p.optString("status","");if(x.smartOrderId.isEmpty())throw new IllegalStateException("Groww GTT id missing");return x;}
    public void cancelGtt(String smartOrderId)throws Exception{if(smartOrderId==null||smartOrderId.isEmpty())return;authed("POST",ROOT+"/order-advance/cancel/CASH/GTT/"+enc(smartOrderId),null,false);}
    public Position getPosition(String symbol,String product)throws Exception{JSONObject r=authed("GET",ROOT+"/positions/trading-symbol?trading_symbol="+enc(symbol)+"&segment=CASH",null,true);JSONObject p=r.optJSONObject("payload");JSONArray a=p==null?null:p.optJSONArray("positions");Position f=new Position();f.symbol=symbol;f.product=product;if(a==null)return f;for(int i=0;i<a.length();i++){JSONObject x=a.optJSONObject(i);if(x==null||!symbol.equalsIgnoreCase(x.optString("trading_symbol","")))continue;String pr=x.optString("product","");if(product!=null&&!product.isEmpty()&&!pr.isEmpty()&&!product.equalsIgnoreCase(pr))continue;Position pos=new Position();pos.symbol=symbol;pos.product=pr;pos.quantity=x.optInt("quantity",0);pos.netPrice=x.optDouble("net_price",0);pos.realisedPnl=x.optDouble("realised_pnl",0);return pos;}return f;}

    private JSONObject authed(String method,String url,String body,boolean retry)throws Exception{String token=ensureToken();HttpResult rr=raw(method,url,body,token,true,false);if(rr.code==401&&retry){clearToken();return authed(method,url,body,false);}if(rr.code<200||rr.code>=300)throw new IllegalStateException("Groww HTTP "+rr.code+": "+safeMsg(rr.body));JSONObject j=new JSONObject(rr.body);if("FAILURE".equalsIgnoreCase(j.optString("status","")))throw new IllegalStateException("Groww failure: "+safeMsg(rr.body));return j;}
    private static HttpResult raw(String method,String url,String body,String bearer,boolean apiVersion,boolean noAuth)throws Exception{if(!noAuth)throttle();HttpURLConnection c=(HttpURLConnection)new URL(url).openConnection();c.setConnectTimeout(7000);c.setReadTimeout(9000);c.setRequestMethod(method);c.setUseCaches(false);c.setRequestProperty("Accept",noAuth?"text/plain":"application/json");if(!noAuth)c.setRequestProperty("Authorization","Bearer "+bearer);if(apiVersion)c.setRequestProperty("X-API-VERSION","1.0");if(body!=null){c.setDoOutput(true);c.setRequestProperty("Content-Type","application/json");try(OutputStream os=c.getOutputStream()){os.write(body.getBytes(StandardCharsets.UTF_8));}}int code=c.getResponseCode();InputStream in=code>=200&&code<400?c.getInputStream():c.getErrorStream();StringBuilder s=new StringBuilder();if(in!=null)try(BufferedReader br=new BufferedReader(new InputStreamReader(in,StandardCharsets.UTF_8))){String line;while((line=br.readLine())!=null)s.append(line).append('\n');}c.disconnect();return new HttpResult(code,s.toString());}
    private static void throttle()throws InterruptedException{synchronized(RATE_LOCK){long now=System.currentTimeMillis(),wait=135-(now-lastApiRequest);if(wait>0)Thread.sleep(wait);lastApiRequest=System.currentTimeMillis();}}

    private static ArrayList<String> clean(List<String> symbols){ArrayList<String> u=new ArrayList<>();if(symbols!=null)for(String s:symbols){if(s==null)continue;s=s.trim().toUpperCase(Locale.ROOT);if(!s.isEmpty()&&!u.contains(s))u.add(s);}return u;}
    private static String join(ArrayList<String> u,int start,int end){StringBuilder b=new StringBuilder();for(int i=start;i<end;i++){if(b.length()>0)b.append(',');b.append("NSE_").append(u.get(i));}return b.toString();}
    private static Ohlc parseOhlcValue(Object raw){if(raw==null)return null;Ohlc o=new Ohlc();if(raw instanceof JSONObject){JSONObject j=(JSONObject)raw;o.open=j.optDouble("open",0);o.high=j.optDouble("high",0);o.low=j.optDouble("low",0);o.close=j.optDouble("close",0);return o;}String s=String.valueOf(raw).replace("{","").replace("}","").replace("\"","");for(String pair:s.split(",")){String[] kv=pair.split(":",2);if(kv.length!=2)continue;try{double v=Double.parseDouble(kv[1].trim());String k=kv[0].trim().toLowerCase(Locale.ROOT);if(k.contains("open"))o.open=v;else if(k.contains("high"))o.high=v;else if(k.contains("low"))o.low=v;else if(k.contains("close"))o.close=v;}catch(Exception ignored){}}return o;}
    private static void parseOhlc(Object o,Db.MarketSnapshot q){Ohlc x=parseOhlcValue(o);if(x!=null){q.dayHigh=x.high;q.dayLow=x.low;}}
    private static void parseTopDepth(JSONObject d,Db.MarketSnapshot q){if(d==null)return;JSONArray b=d.optJSONArray("buy"),s=d.optJSONArray("sell");if(q.bid<=0&&b!=null&&b.length()>0&&b.optJSONObject(0)!=null)q.bid=b.optJSONObject(0).optDouble("price",0);if(q.ask<=0&&s!=null&&s.length()>0&&s.optJSONObject(0)!=null)q.ask=s.optJSONObject(0).optDouble("price",0);}
    private static double depthImbalance(JSONObject d){if(d==null)return 0;JSONArray b=d.optJSONArray("buy"),s=d.optJSONArray("sell");double buy=0,sell=0;double[] w={1,.8,.65,.5,.4};for(int i=0;i<w.length;i++){if(b!=null&&i<b.length()&&b.optJSONObject(i)!=null)buy+=w[i]*b.optJSONObject(i).optDouble("quantity",0);if(s!=null&&i<s.length()&&s.optJSONObject(i)!=null)sell+=w[i]*s.optJSONObject(i).optDouble("quantity",0);}return buy+sell>0?(buy-sell)/(buy+sell):0;}
    private static String totp(String base32,long nowMs)throws Exception{byte[] key=decodeBase32(base32);long counter=nowMs/30000L;byte[] msg=new byte[8];for(int i=7;i>=0;i--){msg[i]=(byte)(counter&0xff);counter>>>=8;}Mac mac=Mac.getInstance("HmacSHA1");mac.init(new SecretKeySpec(key,"HmacSHA1"));byte[] h=mac.doFinal(msg);int off=h[h.length-1]&0x0f;int bin=((h[off]&0x7f)<<24)|((h[off+1]&0xff)<<16)|((h[off+2]&0xff)<<8)|(h[off+3]&0xff);return String.format(Locale.US,"%06d",bin%1000000);}
    private static byte[] decodeBase32(String s){s=s.toUpperCase(Locale.ROOT).replace("=","").replaceAll("[^A-Z2-7]","");java.io.ByteArrayOutputStream out=new java.io.ByteArrayOutputStream();int buffer=0,bits=0;String alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";for(int i=0;i<s.length();i++){int v=alphabet.indexOf(s.charAt(i));if(v<0)continue;buffer=(buffer<<5)|v;bits+=5;if(bits>=8){out.write((buffer>>(bits-8))&0xff);bits-=8;}}return out.toByteArray();}
    private static String reference(String side){String b=Long.toString(System.currentTimeMillis(),36).toUpperCase(Locale.ROOT);return "R360"+("SELL".equals(side)?"S":"B")+b;}
    private static String smartReference(){String b=Long.toString(System.currentTimeMillis(),36).toUpperCase(Locale.ROOT);String x="R3GTT"+b;return x.length()>20?x.substring(0,20):x;}
    private static double round2(double x){return Math.round(x*100.0)/100.0;}
    private static String enc(String s)throws Exception{return URLEncoder.encode(s,"UTF-8");}private static double clamp(double x,double a,double b){return Math.max(a,Math.min(b,x));}private static String safeMsg(String s){if(s==null)return"";return s.length()>500?s.substring(0,500):s;}
    private static final class HttpResult{final int code;final String body;HttpResult(int c,String b){code=c;body=b;}}
    public static final class Ohlc{public double open,high,low,close;}
    public static final class Candle{public double open,high,low,close,volume;}
    public static final class OrderResult{public String orderId,status,remark;}
    public static final class OrderDetail{public String orderId,status;public int quantity,filledQty,remainingQty;public double averageFillPrice;}
    public static final class SmartOrderResult{public String smartOrderId,status;}
    public static final class Position{public String symbol,product;public int quantity;public double netPrice,realisedPnl;}
    public static final class Health{public boolean ok,nse,cash,marketData;public String ucc="",message="";}
}
