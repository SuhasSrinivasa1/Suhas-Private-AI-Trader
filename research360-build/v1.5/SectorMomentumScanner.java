package com.suhas.research360engine;

import android.content.Context;

import java.net.URLDecoder;
import java.time.LocalDate;
import java.time.LocalTime;
import java.time.ZoneId;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Isolated sector-momentum engine.
 * v1.5 evaluates every positive Groww 1D sector, then ranks the best five
 * executable continuation candidates across the union of those green sectors.
 */
public final class SectorMomentumScanner {
    private static final String TRENDING="https://groww.in/stocks/sectors-trending";
    private static final String SECTOR_ROOT="https://groww.in/stocks/sectors/";
    private static final ZoneId IST=ZoneId.of("Asia/Kolkata");
    private static final Pattern TREND_LINK=Pattern.compile("href=[\\\"']([^\\\"']*/stocks/sectors-trending/([^\\\"'?]+)[^\\\"']*)[\\\"']",Pattern.CASE_INSENSITIVE);
    private static final Pattern JSON_SECTOR=Pattern.compile("\\\"(?:sectorName|name)\\\"\\s*:\\s*\\\"([^\\\"]+)\\\"[^{}]{0,500}?\\\"(?:priceChange|changePercentage|changePercent)\\\"\\s*:\\s*\\\"?([+-]?[0-9.]+)",Pattern.CASE_INSENSITIVE);
    private static final Pattern COMPANY_JSON=Pattern.compile("\\\"(?:companyName|company_name|displayName)\\\"\\s*:\\s*\\\"([^\\\"]{2,100})\\\"",Pattern.CASE_INSENSITIVE);
    private static final Pattern STOCK_LINK=Pattern.compile("<a[^>]+href=[\\\"']/stocks/([^\\\"'?#/]+)[^\\\"']*[\\\"'][^>]*>(.*?)</a>",Pattern.CASE_INSENSITIVE|Pattern.DOTALL);

    private final Context context;private final GrowwClient groww;private final Db db;private long lastAttempt=0;
    public SectorMomentumScanner(Context c,GrowwClient g){context=c.getApplicationContext();groww=g;db=Db.get(c);}

    public void maybeRun(){
        LocalTime n=LocalTime.now(IST);if(n.isBefore(LocalTime.of(9,18))||n.isAfter(LocalTime.of(14,45)))return;
        long now=System.currentTimeMillis();if(now-lastAttempt<6L*60L*1000L)return;lastAttempt=now;
        try{scan();}catch(Exception e){AppState.setSectorState(context,"",0,"Groww positive-sector scan unavailable — NO SECTOR TRADE • "+shortMsg(e));db.log("SECTOR","Fail-closed: "+shortMsg(e));}
    }

    public void scan()throws Exception{
        String trending=groww.fetchPublicText(TRENDING);List<SectorRow> positives=parsePositiveSectors(trending);
        if(positives.isEmpty())throw new IllegalStateException("no positive Groww 1D sectors could be verified");
        List<Instrument> instruments=parseInstrumentMaster(groww.downloadInstrumentCsv());if(instruments.isEmpty())throw new IllegalStateException("instrument master unavailable");

        LinkedHashMap<String,Seed> symbolSeeds=new LinkedHashMap<>();int sectorPages=0;
        for(SectorRow sector:positives){
            try{
                String html=groww.fetchPublicText(SECTOR_ROOT+sector.slug);sectorPages++;
                List<String> companies=parseCompanies(html);List<String> symbols=matchSymbols(companies,instruments);int accepted=0;
                for(String symbol:symbols){if(accepted++>=80)break;Seed old=symbolSeeds.get(symbol);if(old==null||sector.pct>old.sector.pct){Seed seed=new Seed();seed.symbol=symbol;seed.sector=sector;symbolSeeds.put(symbol,seed);}}
            }catch(Exception ignored){}
        }
        if(symbolSeeds.size()<3)throw new IllegalStateException("positive sectors verified but constituents could not be resolved");

        ArrayList<String> symbols=new ArrayList<>(symbolSeeds.keySet());if(symbols.size()>1500)symbols=new ArrayList<>(symbols.subList(0,1500));
        Map<String,Double> ltps=groww.getLtps(symbols);Map<String,GrowwClient.Ohlc> ohlc=groww.getOhlc(symbols);ArrayList<Candidate> stage=new ArrayList<>();
        for(String symbol:symbols){
            Seed seed=symbolSeeds.get(symbol);Double px=ltps.get(symbol);GrowwClient.Ohlc o=ohlc.get(symbol);
            if(seed==null||px==null||px<=0||o==null||o.open<=0||o.high<=0||o.low<=0)continue;if(px<5||px>AppState.budget(context)*1.25)continue;
            Candidate c=new Candidate();c.symbol=symbol;c.sector=seed.sector;c.price=px;c.day=(px/o.open-1)*100.0;c.range=o.high>o.low?(px-o.low)/(o.high-o.low):.5;
            Db.SectorPerf hist=db.sectorPerf(c.sector.name);c.histTrades=hist.trades;c.histWin=hist.winRate();c.histAvg=hist.avgNet;
            c.base=46.0+clamp(c.sector.pct,0,10)*2.6+clamp(c.day,0,7)*2.0;
            if(c.day<0)c.base-=12;if(c.day>=.15&&c.day<=6)c.base+=5;if(c.day>10)c.base-=8;if(c.range>=.55&&c.range<=.94)c.base+=5;else if(c.range>.985)c.base-=8;else if(c.range<.35)c.base-=5;
            if(hist.trades>=5){c.base+=clamp((hist.winRate()-.50)*18.0,-5,7);c.base+=clamp(hist.avgNet/45.0,-4,6);}stage.add(c);
        }
        if(stage.isEmpty())throw new IllegalStateException("no executable stocks found inside positive sectors");stage.sort((a,b)->Double.compare(b.base,a.base));if(stage.size()>30)stage=new ArrayList<>(stage.subList(0,30));

        ArrayList<Candidate> deep=new ArrayList<>();for(Candidate c:stage){try{Db.MarketSnapshot q=groww.getQuote(c.symbol);c.q=q;c.score=score(c,q);deep.add(c);}catch(Exception ignored){}}deep.sort((a,b)->Double.compare(b.score,a.score));
        ArrayList<Candidate> picked=new ArrayList<>();for(Candidate c:deep){if(picked.size()>=5)break;if(c.q==null||c.q.ltp<=0)continue;if(c.q.spreadBps>40||c.q.rangePosition>.997||c.q.dayChangePct>15)continue;if(c.score<62)continue;picked.add(c);}if(picked.isEmpty())throw new IllegalStateException("positive sectors found but no stock passed liquidity / late-chase checks");

        long recent=System.currentTimeMillis()-24L*60L*1000L;SectorRow leader=positives.get(0);StringBuilder summary=new StringBuilder(String.format(Locale.US,"Positive Groww sectors: %d • leader %s %+,.2f%% • scanned %d sector pages / %d NSE stocks\n",positives.size(),leader.name,leader.pct,sectorPages,symbols.size()));
        summary.append("Green sectors: ");for(int i=0;i<Math.min(8,positives.size());i++){SectorRow s=positives.get(i);if(i>0)summary.append(" • ");summary.append(s.name).append(String.format(Locale.US," %+,.2f%%",s.pct));}if(positives.size()>8)summary.append(" • +").append(positives.size()-8).append(" more");summary.append("\nTOP 5 ACROSS ALL POSITIVE SECTORS\n");
        int rank=1;for(Candidate c:picked){if(!db.hasRecentSignal("SECTOR_MOMENTUM_INTRADAY","BUY",c.symbol,c.q.ltp,recent))db.insertSectorSignal(c.symbol,c.q.ltp,c.score,c.sector.name,c.sector.pct,c.q.dayChangePct);summary.append(String.format(Locale.US,"%d. %s • %s %+,.2f%% • %.0f%% • ₹%.2f • stock Δ %.2f%% • DI %.2f • %.1fbps\n",rank++,c.symbol,c.sector.name,c.sector.pct,c.score,c.q.ltp,c.q.dayChangePct,c.q.depthImbalance,c.q.spreadBps));}
        summary.append("Learning compartment: SECTOR ONLY • persisted across sessions • no cross-training");AppState.setSectorState(context,leader.name,leader.pct,summary.toString().trim());AppState.setLastSectorScan(context,LocalDate.now(IST).toString());db.log("SECTOR",String.format(Locale.US,"%d positive sectors • leader %s %+,.2f%% • %d global Top-5 picks",positives.size(),leader.name,leader.pct,picked.size()));
    }

    private static double score(Candidate c,Db.MarketSnapshot q){double x=c.base;x+=clamp(q.depthImbalance,-.60,.70)*13.0;if(q.spreadBps>0){if(q.spreadBps<=5)x+=7;else if(q.spreadBps<=12)x+=4;else if(q.spreadBps<=25)x+=1;else x-=9;}if(q.rangePosition>=.55&&q.rangePosition<=.92)x+=7;else if(q.rangePosition>.98)x-=8;else if(q.rangePosition<.35)x-=4;if(q.averagePrice>0){double ext=(q.ltp/q.averagePrice-1)*100.0;if(ext>=0&&ext<=1.8)x+=6;else if(ext>3.5)x-=8;else if(ext<-.4)x-=5;}if(q.volume>0)x+=clamp(Math.log10(q.volume+1)-4,0,2.5)*2.0;if(q.dayChangePct>10)x-=4;if(q.dayChangePct<0)x-=10;return clamp(x,0,94);}

    private static List<SectorRow> parsePositiveSectors(String html){LinkedHashMap<String,SectorRow> rows=new LinkedHashMap<>();if(html==null||html.isEmpty())return new ArrayList<>();Matcher m=TREND_LINK.matcher(html);while(m.find()){String slug=m.group(2)==null?"":m.group(2).toLowerCase(Locale.ROOT);if(slug.isEmpty()||slug.equals("trending")||slug.equals("industries"))continue;int ae=Math.min(html.length(),m.end()+700);double pct=firstPct(strip(html.substring(m.end(),ae)));if(Double.isNaN(pct))pct=firstPct(strip(html.substring(Math.max(0,m.start()-120),Math.min(html.length(),m.end()+500))));if(!Double.isNaN(pct)&&pct>0){SectorRow r=new SectorRow();r.slug=slug;r.name=title(slug);r.pct=pct;SectorRow old=rows.get(slug);if(old==null||pct>old.pct)rows.put(slug,r);}}
        Matcher j=JSON_SECTOR.matcher(html);while(j.find()){String name=unescape(j.group(1)).trim();double pct;try{pct=Double.parseDouble(j.group(2));}catch(Exception e){continue;}if(name.isEmpty()||pct<=0)continue;String slug=slugify(name);if(slug.isEmpty())continue;if(!rows.containsKey(slug)){SectorRow r=new SectorRow();r.name=name;r.slug=slug;r.pct=pct;rows.put(slug,r);}}
        ArrayList<SectorRow> out=new ArrayList<>(rows.values());out.sort((a,b)->Double.compare(b.pct,a.pct));if(out.size()>80)out=new ArrayList<>(out.subList(0,80));return out;}
    private static List<String> parseCompanies(String html){ArrayList<String> out=new ArrayList<>();Set<String> seen=new HashSet<>();Matcher j=COMPANY_JSON.matcher(html);while(j.find()&&out.size()<120){String n=cleanCompany(unescape(j.group(1)));if(n.length()>2&&seen.add(norm(n)))out.add(n);}Matcher a=STOCK_LINK.matcher(html);while(a.find()&&out.size()<120){String n=cleanCompany(strip(a.group(2)));if(n.length()>2&&!isGeneric(n)&&seen.add(norm(n)))out.add(n);}return out;}
    private static List<Instrument> parseInstrumentMaster(String csv){ArrayList<Instrument> out=new ArrayList<>();if(csv==null)return out;String[] lines=csv.split("\\r?\\n");if(lines.length<2)return out;List<String> h=parseCsv(lines[0]);Map<String,Integer> ix=new HashMap<>();for(int i=0;i<h.size();i++)ix.put(h.get(i).trim().toLowerCase(Locale.ROOT),i);int ie=i(ix,"exchange"),is=i(ix,"segment"),it=i(ix,"trading_symbol"),in=i(ix,"name"),id=i(ix,"display_name"),iser=i(ix,"series");for(int k=1;k<lines.length;k++){List<String> r=parseCsv(lines[k]);if(!"NSE".equalsIgnoreCase(get(r,ie))||!"CASH".equalsIgnoreCase(get(r,is)))continue;if(iser>=0&&!get(r,iser).isEmpty()&&!"EQ".equalsIgnoreCase(get(r,iser)))continue;String sym=get(r,it);if(sym.isEmpty())continue;String name=in>=0?get(r,in):"";if(name.isEmpty()&&id>=0)name=get(r,id);Instrument x=new Instrument();x.symbol=sym.toUpperCase(Locale.ROOT);x.name=name;x.norm=norm(name);out.add(x);}return out;}
    private static List<String> matchSymbols(List<String> names,List<Instrument> ins){ArrayList<String> out=new ArrayList<>();for(String name:names){String n=norm(name);Instrument best=null;int bs=0;for(Instrument x:ins){if(x.norm.isEmpty())continue;int sc=similarity(n,x.norm);if(sc>bs){bs=sc;best=x;}}if(best!=null&&bs>=72&&!out.contains(best.symbol))out.add(best.symbol);}return out;}
    private static int similarity(String a,String b){if(a.equals(b))return 100;if(a.isEmpty()||b.isEmpty())return 0;if(a.contains(b)||b.contains(a))return 88;String[] aa=a.split(" "),bb=b.split(" ");int hit=0;for(String x:aa)if(x.length()>2)for(String y:bb)if(x.equals(y)){hit++;break;}int den=Math.max(1,Math.max(aa.length,bb.length));return (int)Math.round(100.0*hit/den);}
    private static double firstPct(String s){Matcher m=Pattern.compile("([+-]?[0-9]+(?:\\.[0-9]+)?)\\s*%").matcher(s);if(m.find())try{return Double.parseDouble(m.group(1));}catch(Exception ignored){}return Double.NaN;}
    private static String slugify(String s){return norm(s).replace(' ','-');}private static String title(String slug){StringBuilder b=new StringBuilder();for(String p:slug.split("-")){if(p.isEmpty())continue;if(b.length()>0)b.append(' ');b.append(Character.toUpperCase(p.charAt(0))).append(p.substring(1));}return b.toString();}
    private static String norm(String s){return unescape(s).toLowerCase(Locale.ROOT).replace("&"," and ").replaceAll("\\b(limited|ltd|industries|industry|company|co)\\b"," ").replaceAll("[^a-z0-9]+"," ").trim().replaceAll("\\s+"," ");}
    private static String cleanCompany(String s){return unescape(s).replaceAll("\\s+"," ").trim();}private static boolean isGeneric(String s){String x=s.toLowerCase(Locale.ROOT);return x.contains("sector")||x.equals("stocks")||x.equals("see more")||x.equals("home");}
    private static String strip(String s){return unescape(s.replaceAll("<script[^>]*>.*?</script>"," ").replaceAll("<[^>]+>"," ")).replaceAll("\\s+"," ").trim();}private static String unescape(String s){if(s==null)return"";return s.replace("&amp;","&").replace("&#39;","'").replace("&quot;","\"").replace("\\u0026","&");}
    private static String decode(String s){try{return URLDecoder.decode(s,"UTF-8");}catch(Exception e){return s;}}
    private static List<String> parseCsv(String s){ArrayList<String> r=new ArrayList<>();StringBuilder b=new StringBuilder();boolean q=false;for(int j=0;j<s.length();j++){char ch=s.charAt(j);if(ch=='\"'){if(q&&j+1<s.length()&&s.charAt(j+1)=='\"'){b.append('\"');j++;}else q=!q;}else if(ch==','&&!q){r.add(b.toString());b.setLength(0);}else b.append(ch);}r.add(b.toString());return r;}private static int i(Map<String,Integer> m,String k){Integer x=m.get(k);return x==null?-1:x;}private static String get(List<String> r,int i){return i>=0&&i<r.size()?r.get(i).trim():"";}
    private static double clamp(double x,double a,double b){return Math.max(a,Math.min(b,x));}private static String shortMsg(Exception e){String s=e.getMessage();return s==null?e.getClass().getSimpleName():s.substring(0,Math.min(160,s.length()));}
    private static final class SectorRow{String name="",slug="";double pct;}private static final class Instrument{String symbol,name,norm;}private static final class Seed{String symbol;SectorRow sector;}private static final class Candidate{String symbol;SectorRow sector;double price,day,range,base,score,histWin,histAvg;long histTrades;Db.MarketSnapshot q;}
}
