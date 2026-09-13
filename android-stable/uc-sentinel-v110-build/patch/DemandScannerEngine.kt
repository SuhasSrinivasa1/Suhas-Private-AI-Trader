package com.suhas.ucsentinel.domain.engine

import com.suhas.ucsentinel.data.remote.GrowwClient
import com.suhas.ucsentinel.domain.model.*
import kotlinx.coroutines.delay
import java.time.ZoneId
import java.time.ZonedDateTime
import java.time.format.DateTimeFormatter
import kotlin.math.max

class DemandScannerEngine(
    private val growwClient: GrowwClient,
    private val signalEngine: DemandSignalEngine = DemandSignalEngine()
) {
    private val ist = ZoneId.of("Asia/Kolkata")
    private val fmt = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss")

    suspend fun scan(
        accessToken: String,
        universe: List<Instrument>,
        newListings: List<ListedSecurity>,
        settings: AppSettings,
        adaptivePrecision: Map<String, Double> = emptyMap(),
        progress: suspend (String)->Unit = {}
    ): ScanSummary {
        val started = System.currentTimeMillis()
        val newMap = newListings.associateBy { it.symbol }
        val allowedSeries = if(settings.includeSmeSeries) setOf("EQ","BE","BZ","SM","ST") else setOf("EQ","BE","BZ")
        val cash = universe.filter { it.exchange=="NSE" && it.segment=="CASH" && it.series in allowedSeries && it.buyAllowed }
        val prelim = mutableListOf<Pair<Instrument,Ohlc>>()

        progress("Demand scan: screening ${cash.size} NSE cash stocks")
        cash.chunked(50).forEachIndexed { idx,batch ->
            val map = growwClient.getOhlcBatch(accessToken,batch.map{it.tradingSymbol})
            batch.forEach { i ->
                val o=map[i.tradingSymbol]?:return@forEach
                if(o.close<=0||o.high<=0||o.open<=0) return@forEach
                val closeLocation=if(o.high<=o.low)1.0 else (o.close-o.low)/(o.high-o.low)
                val openReturn=(o.close/o.open-1)*100
                val isNew = newMap.containsKey(i.tradingSymbol)
                if(isNew || closeLocation>=.72 || openReturn>=1.0) prelim += i to o
            }
            progress("Demand pre-screen ${((idx+1)*50).coerceAtMost(cash.size)}/${cash.size}")
            delay(200)
        }

        val ranked = prelim.sortedByDescending { (i,o) ->
            val isNew=if(newMap.containsKey(i.tradingSymbol))5.0 else 0.0
            val loc=if(o.high<=o.low)1.0 else (o.close-o.low)/(o.high-o.low)
            val ret=(o.close/o.open-1)*100
            isNew + loc*3 + ret.coerceAtMost(10.0)
        }.take(settings.maxQuotesPerScan)

        val candidates=mutableListOf<Candidate>()
        for((index,pair) in ranked.withIndex()) {
            val instrument=pair.first
            val quote=runCatching{growwClient.getQuote(accessToken,instrument.tradingSymbol)}.getOrNull()?:continue
            val ratio=if(quote.totalSellQuantity<=0) if(quote.totalBuyQuantity>0)99.0 else 0.0 else quote.totalBuyQuantity.toDouble()/quote.totalSellQuantity
            val supplyThin = quote.totalSellQuantity <= max(20L, quote.totalBuyQuantity/3)
            val isNew = newMap[instrument.tradingSymbol]
            if(ratio<1.8 && !supplyThin && isNew==null) continue

            val now=ZonedDateTime.now(ist)
            val dailyStart=now.minusDays(100).toLocalDate().atStartOfDay().format(fmt)
            val dailyEnd=now.plusDays(1).toLocalDate().atStartOfDay().format(fmt)
            val intraStart=now.toLocalDate().atTime(9,15).format(fmt)
            val intraEnd=now.toLocalDate().atTime(15,30).format(fmt)
            val daily=runCatching{growwClient.getHistoricalCandles(accessToken,instrument.tradingSymbol,dailyStart,dailyEnd,"1day")}.getOrDefault(emptyList())
            delay(200)
            val intraday=runCatching{growwClient.getHistoricalCandles(accessToken,instrument.tradingSymbol,intraStart,intraEnd,"5minute")}.getOrDefault(emptyList())
            val listingAge=isNew?.daysListed ?: daily.size.takeIf{it in 1..45}?.toLong()
            val results=signalEngine.evaluate(DemandSignalEngine.Context(quote,daily,intraday,listingAge))
            var score=signalEngine.score(results,adaptivePrecision)
            if(ratio>=10) score+=4
            if(quote.totalSellQuantity<=10) score+=4
            if(listingAge!=null && listingAge<=15) score+=2
            score=score.coerceIn(0.0,100.0)
            if(score<settings.demandMinScore) continue

            val avgVol=Indicators.avgVolume(daily.dropLast(1),20)
            val volRatio=if(avgVol<=0)0.0 else quote.volume/avgVol
            val confidence=when{score>=90->ConfidenceBand.VERY_HIGH;score>=82->ConfidenceBand.HIGH;score>=75->ConfidenceBand.MEDIUM;else->ConfidenceBand.LOW}
            candidates += Candidate(
                symbol=instrument.tradingSymbol,
                companyName=instrument.name,
                kind=if(listingAge!=null&&listingAge<=45) CandidateKind.POST_LISTING else CandidateKind.SEASONED,
                section=ScannerSection.DEMAND_SQUEEZE,
                price=quote.lastPrice,
                upperCircuit=quote.upperCircuit,
                dayChangePercent=quote.dayChangePercent,
                score=score,
                confidence=confidence,
                passedSignals=results.count{it.passed},
                totalSignals=results.size,
                buySellRatio=ratio,
                volumeRatio=volRatio,
                consecutiveCircuitLikeDays=Indicators.consecutiveCircuitLikeDays(daily),
                signals=results,
                activeStrategies=signalEngine.activeStrategies(results),
                listingAgeDays=listingAge
            )
            progress("Demand analysis ${index+1}/${ranked.size}: ${instrument.tradingSymbol}")
            delay(200)
        }

        val final=candidates.sortedWith(compareByDescending<Candidate>{it.score}.thenByDescending{it.buySellRatio}.thenByDescending{it.volumeRatio})
            .take(settings.maxDemandCandidates)
        return ScanSummary(
            section=ScannerSection.DEMAND_SQUEEZE,
            startedAt=started,
            completedAt=System.currentTimeMillis(),
            universeCount=cash.size,
            preliminaryCount=ranked.size,
            quotedCount=ranked.size,
            candidates=final,
            newListingsScanned=newListings.size,
            message=if(final.isEmpty())"NO HIGH-DEMAND / LOW-SUPPLY CANDIDATE" else "${final.size} demand-squeeze candidate(s)"
        )
    }
}
