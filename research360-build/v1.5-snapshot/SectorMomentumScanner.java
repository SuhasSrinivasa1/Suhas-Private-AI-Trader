package com.suhas.research360engine;

import android.content.Context;

import java.net.URLDecoder;
import java.time.LocalDate;
import java.time.LocalTime;
import java.time.ZoneId;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Isolated sector-momentum engine. Groww's public "Trending sectors" table is the sector oracle.
 * If the Groww leader cannot be verified, this engine fails closed and does not guess a sector.
 */
public final class SectorMomentumScanner {
    private static final String TRENDING="https://groww.in/stocks/sectors-trending";
    private static final String SECTOR_ROOT="https://groww.in/stocks/sectors/";
    private static final ZoneId IST=ZoneId.of("Asia/Kolkata");
    private static final Pattern TREND_LINK=Pattern.compile("href=[\\\"']([^\\\"']*/stocks/sectors-trending/([^\\\"'?]+)[^\\\"']*)[\\\"']",Pattern.CASE_INSENSITIVE);
    private static final Pattern JSON_SECTOR=Pattern.compile("\\\"(?:sectorName|name)\\\"\\s*:\\s*\\\"([^\\\"]+)\\\"[^{}]{0,500}?\\\"(?:priceChange|changePercentage|changePercent)\\\"\\s*:\\s*\\\"?([+-]?[0-9.]+)",Pattern.CASE_INSENSITIVE);
    private static final Pattern COMPANY_JSON=Pattern.compile("\\\"(?:companyName|company_name|displayName)\\\"\\s*:\\s*\\\"([^\\\"]{2,100})\\\"",Pattern.CASE_INSENSITIVE);
    private static final Pattern STOCK_LINK=Pattern.compile("<a[^>]+href=[\\\"']/stocks/([^\\\"'?#/]+)[^\\\"']*[\\\"'][^>]*>(.*?)</a>",Pattern.CASE_INSENSITIVE|Pattern.DOTALL);
    private final Context context;private final GrowwClient groww;private final Db db;
    private long lastAttempt=0;

    public SectorMomentumScanner(Context c,GrowwClient g){context=c.getApplicationContext();groww=g;db=Db.get(c);}

    public void maybeRun(){
        LocalTime n=LocalTime.now(IST);if(n.isBefore(LocalTime.of(9,18))||n.isAfter(LocalTime.of(14,45)))return;
        long now=System.currentTimeMillis();if(now-lastAttempt<4L*60L*1000L)return;lastAttempt=now;
        try{scan();}catch(Exception e){AppState.setSectorState(context,"",0,"Groww sector oracle unavailable — NO SECTOR TRADE • "+shortMsg(e));db.log("SECTOR","Fail-closed: "+shortMsg(e));}
    }

    public void scan()throws Exception{
        String trending=groww.fetchPublicText(TRENDING);Leader leader=parseLeader(trending);
        if(leader==null||leader.name.isEmpty())throw new IllegalStateException("could not verify first Groww trending-sector row");
        if(leader.pct<=0)throw new IllegalStateException("Groww top sector is not positive");
        String slug=leader.slug.isEmpty()?slugify(leader.name):leader.slug;
        String sectorHtml=groww.fetchPublicText(SECTOR_ROOT+slug);
        List<String> companyNames=parseCompanies(sectorHtml);if(companyNames.size()<2)throw new IllegalStateException("no reliable constituent list for "+leader.name);
        List<Instrument> instruments=parseInstrumentMaster(groww.downloadInstrumentCsv());List<String> symbols=matchSymbols(companyNames,instruments);
        if(symbols.size()<2)throw new IllegalStateException("could not match enough NSE constituents for "+leader.name);

        Map<String,Double> ltps=groww.getLtps(symbols);Map<String,GrowwClient.Ohlc> ohlc=groww.getOhlc(symbols);ArrayList<Candidate> stage=new ArrayList<>();
        for(String s:symbols){Double px=ltps.get(s);GrowwClient.Ohlc o=ohlc.get(s);if(px==null||px<=0||o==null||o.open<=0||o.high<=0||o.low<=0)continue;if(px<5||px>AppState.budget(context)*1.25)continue;Candidate c=new Candidate();c.symbol=s;c.price=px;c.day=(px/o.open-1)*100;c.range=o.high>o.low?(px-o.low)/(o.high-o.low):.5;c.base=54+clamp(c.day,0,5)*4.0;if(c.day<.15)c.base-=10;if(c.day>9)c.base-=12;if(c.range>.985)c.base-=8;if(c.range<.40)c.base-=6;stage.add(c);}
        stage.sort((a,b)->Double.compare(b.base,a.base));if(stage.size()>12)stage=new ArrayList<>(stage.subList(0,12));
        ArrayList<Candidate> deep=new ArrayList<>();for(Candidate c:stage){try{Db.MarketSnapshot q=groww.getQuote(c.symbol);c.q=q;c.score=score(c,q,leader.pct);deep.add(c);}catch(Exception ignored){}}
        deep.sort((a,b)->Double.compare(b.score,a.score));ArrayList<Candidate> picked=new ArrayList<>();
        for(Candidate c:deep){if(picked.size()>=3)break;if(c.q==null||c.q.ltp<=0)continue;if(c.q.spreadBps>35||c.q.rangePosition>.995||c.q.dayChangePct>12)continue;if(c.score<64)continue;picked.add(c);}
        if(picked.isEmpty())throw new IllegalStateException("leader verified but no executable continuation candidate passed liquidity/chase checks");

        StringBuilder summary=new StringBuilder(String.format(Locale.US,"Groww leader: %s %+,.2f%% • verified from Trending sectors (1D price change)\n",leader.name,leader.pct));
        int rank=1;for(Candidate c:picked){
            long recent=System.currentTimeMillis()-25L*60L*1000L;if(!db.hasRecentSignal("SECTOR_MOMENTUM_INTRADAY","BUY",c.symbol,c.q.ltp,recent))db.insertModelSignal("SECTOR_MOMENTUM_INTRADAY",c.symbol,c.q.ltp,c.score);
            summary.append(String.format(Locale.US,"%d. %s • %.0f%% • ₹%.2f • Δ %.2f%% • DI %.2f • %.1fbps\n",rank++,c.symbol,c.score,c.q.ltp,c.q.dayChangePct,c.q.depthImbalance,c.q.spreadBps));
        }
        summary.append("Learning compartment: SECTOR ONLY • no cross-training");AppState.setSectorState(context,leader.name,leader.pct,summary.toString().trim());AppState.setLastSectorScan(context,LocalDate.now(IST).toString());db.log("SECTOR","Groww oracle confirmed "+leader.name+String.format(Locale.US," %+,.2f%% • %d picks",leader.pct,picked.size()));
    }

    private static double score(Candidate c,Db.MarketSnapshot q,double sectorPct){double x=c.base;x+=clamp(sectorPct,0,6)*2.0;x+=clamp(q.depthImbalance,-.55,.65)*13;if(q.spreadBps>0){if(q.spreadBps<=5)x+=7;else if(q.spreadBps<=12)x+=3;else if(q.spreadBps>25)x-=10;}if(q.rangePosition>=.55&&q.rangePosition<=.91)x+=7;else if(q.rangePosition>.975)x-=9;if(q.averagePrice>0&&q.ltp>=q.averagePrice)x+=6;if(q.volume>0)x+=clamp(Math.log10(q.volume+1)-4,0,2.5)*2;if(q.dayChangePct>8)x-=5;return clamp(x,0,94);}

    private static Leader parseLeader(String html){if(html==null||html.isEmpty())return null;
        // Prefer the first actual trending-sector link in page order. Header/navigation sector links are skipped.
        Matcher m=TREND_LINK.matcher(html);while(m.find()){String href=decode(m.group(1)),slug=m.group(2);if(slug==null)continue;slug=slug.toLowerCase(Locale.ROOT);if(slug.equals("trending")||slug.equals("industries"))continue;String around=strip(html.substring(Math.max(0,m.start()-220),Math.min(html.length(),m.end()+400)));double pct=firstPct(around);if(!Double.isNaN(pct)){Leader l=new Leader();l.slug=slug;l.name=title(slug);l.pct=pct;return l;}}
        Matcher j=JSON_SECTOR.matcher(html);if(j.find()){Leader l=new Leader();l.name=unescape(j.group(1));try{l.pct=Double.parseDouble(j.group(2));}catch(Exception e){return null;}l.slug=slugify(l.name);return l;}return null;}
    private static List<String> parseCompanies(String html){ArrayList<String> out=new ArrayList<>();Set<String> seen=new HashSet<>();Matcher j=COMPANY_JSON.matcher(html);while(j.find()&&out.size()<80){String n=cleanCompany(unescape(j.group(1)));if(n.length()>2&&seen.add(norm(n)))out.add(n);}Matcher a=STOCK_LINK.matcher(html);while(a.find()&&out.size()<80){String n=cleanCompany(strip(a.group(2)));if(n.length()>2&&!isGeneric(n)&&seen.add(norm(n)))out.add(n);}return out;}
    private static List<Instrument> parseInstrumentMaster(String csv){ArrayList<Instrument> out=new ArrayList<>();if(csv==null)return out;String[] lines=csv.split("\\r?\\n");if(lines.length<2)return out;List<String> h=parseCsv(lines[0]);Map<String,Integer> ix=new HashMap<>();for(int i=0;i<h.size();i++)ix.put(h.get(i).trim().toLowerCase(Locale.ROOT),i);int ie=i(ix,"exchange"),is=i(ix,"segment"),it=i(ix,"trading_symbol"),in=i(ix,"name"),id=i(ix,"display_name"),iser=i(ix,"series");for(int k=1;k<lines.length;k++){List<String> r=parseCsv(lines[k]);if(!"NSE".equalsIgnoreCase(get(r,ie))||!"CASH".equalsIgnoreCase(get(r,is)))continue;if(iser>=0&&!get(r,iser).isEmpty()&&!"EQ".equalsIgnoreCase(get(r,iser)))continue;String sym=get(r,it);if(sym.isEmpty())continue;String name=in>=0?get(r,in):"";if(name.isEmpty()&&id>=0)name=get(r,id);Instrument x=new Instrument();x.symbol=sym.toUpperCase(Locale.ROOT);x.name=name;x.norm=norm(name);out.add(x);}return out;}
    private static List<String> matchSymbols(List<String> names,List<Instrument> ins){ArrayList<String> out=new ArrayList<>();for(String name:names){String n=norm(name);Instrument best=null;int bs=0;for(Instrument x:ins){if(x.norm.isEmpty())continue;int sc=similarity(n,x.norm);if(sc>bs){bs=sc;best=x;}}if(best!=null&&bs>=72&&!out.contains(best.symbol))out.add(best.symbol);}return out;}
    private static int similarity(String a,String b){if(a.equals(b))return 100;if(a.isEmpty()||b.isEmpty())return 0;if(a.contains(b)||b.contains(a))return 88;String[] aa=a.split(" "),bb=b.split(" ");int hit=0;for(String x:aa)if(x.length()>2)for(String y:bb)if(x.equals(y)){hit++;break;}int den=Math.max(1,Math.max(aa.length,bb.length));return (int)Math.round(100.0*hit/den);}
    private static double firstPct(String s){Matcher m=Pattern.compile("([+-]?[0-9]+(?:\\.[0-9]+)?)\\s*%").matcher(s);if(m.find())try{return Double.parseDouble(m.group(1));}catch(Exception ignored){}return Double.NaN;}
    private static String slugify(String s){return norm(s).replace(' ','-');}private static String title(String slug){StringBuilder b=new StringBuilder();for(String p:slug.split("-")){if(p.isEmpty())continue;if(b.length()>0)b.append(' ');b.append(Character.toUpperCase(p.charAt(0))).append(p.substring(1));}return b.toString();}
    private static String norm(String s){return unescape(s).toLowerCase(Locale.ROOT).replace("&"," and ").replaceAll("\\b(limited|ltd|industries|industry|company|co)\\b"," ").replaceAll("[^a-z0-9]+"," ").trim().replaceAll("\\s+"," ");}
    private static String cleanCompany(String s){return unescape(s).replaceAll("\\s+"," ").trim();}private static boolean isGeneric(String s){String x=s.toLowerCase(Locale.ROOT);return x.contains("sector")||x.equals("stocks")||x.equals("see more")||x.equals("home");}
    private static String strip(String s){return unescape(s.replaceAll("<script[^>]*>.*?</script>"," ").replaceAll("<[^>]+>"," ")).replaceAll("\\s+"," ").trim();}
    private static String unescape(String s){if(s==null)return"";return s.replace("&amp;","&").replace("&#39;","'").replace("&quot;","\"").replace("\\u0026","&");}
    private static String decode(String s){try{return URLDecoder.decode(s,"UTF-8");}catch(Exception e){return s;}}
    private static List<String> parseCsv(String s){ArrayList<String> r=new ArrayList<>();StringBuilder b=new StringBuilder();boolean q=false;for(int j=0;j<s.length();j++){char ch=s.charAt(j);if(ch=='\"'){if(q&&j+1<s.length()&&s.charAt(j+1)=='\"'){b.append('\"');j++;}else q=!q;}else if(ch==','&&!q){r.add(b.toString());b.setLength(0);}else b.append(ch);}r.add(b.toString());return r;}private static int i(Map<String,Integer> m,String k){Integer x=m.get(k);return x==null?-1:x;}private static String get(List<String> r,int i){return i>=0&&i<r.size()?r.get(i).trim():"";}
    private static double clamp(double x,double a,double b){return Math.max(a,Math.min(b,x));}private static String shortMsg(Exception e){String s=e.getMessage();return s==null?e.getClass().getSimpleName():s.substring(0,Math.min(160,s.length()));}
    private static final class Leader{String name="",slug="";double pct;}private static final class Instrument{String symbol,name,norm;}private static final class Candidate{String symbol;double price,day,range,base,score;Db.MarketSnapshot q;}
}
