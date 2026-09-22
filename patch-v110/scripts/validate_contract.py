from pathlib import Path

root = Path(__file__).resolve().parents[1]
java = (root / 'app/src/main/java/com/suhas/multyfideliverybuy/GrowwClient.java').read_text()
service = (root / 'app/src/main/java/com/suhas/multyfideliverybuy/MultyfiNotificationService.java').read_text()
main = (root / 'app/src/main/java/com/suhas/multyfideliverybuy/MainActivity.java').read_text()
network = (root / 'app/src/main/java/com/suhas/multyfideliverybuy/NetworkCheck.java').read_text()
instruments = (root / 'app/src/main/java/com/suhas/multyfideliverybuy/InstrumentRepository.java').read_text()
manifest = (root / 'app/src/main/AndroidManifest.xml').read_text()
gradle = (root / 'app/build.gradle').read_text()

checks = {
    'same package': "applicationId 'com.suhas.multyfideliverybuy'" in gradle,
    'version 1.1.0': "versionName '1.1.0'" in gradle and 'versionCode 110' in gradle,
    'Multyfi auto path remains CNC': 'placeDeliveryMarketBuy' in service and '"CNC"' in java,
    'Multyfi auto path remains BUY only': 'placeDeliveryMarketBuy' in service and '"SELL"' not in service and '"MIS"' not in service,
    'Multyfi budget unchanged': '== CallParser.Category.INTRADAY ? 100000 : 10000' in service,
    'manual long present': 'executeManualLong' in java and 'BUY LONG + SET 1% GTT' in main,
    'manual long CNC': 'isLong ? "CNC" : "MIS"' in java,
    'manual short present': 'executeManualShort' in java and 'OPEN SHORT + SET 1% TARGET' in main,
    'manual short is SELL MIS': 'isLong ? "BUY" : "SELL"' in java and 'isLong ? "CNC" : "MIS"' in java,
    'one percent long target': 'fill.averagePrice * 1.01' in java,
    'one percent short target': 'fill.averagePrice * 0.99' in java,
    'GTT smart order': '/v1/order-advance/create' in java and 'body.put("smart_order_type", "GTT")' in java,
    'long GTT is broker SELL target': 'createGttTarget(context, instrument.symbol, fill.quantity, "CNC"' in java and '"SELL", "UP", target' in java,
    'short target is DAY LIMIT BUY MIS': 'submitShortCoverLimit' in java and 'body.put("product", "MIS")' in java and 'body.put("order_type", "LIMIT")' in java and 'body.put("transaction_type", "BUY")' in java,
    'short target is not persistent GTT': 'GTT BUY-to-cover' not in java,
    'no stop loss payload': 'stop_loss' not in java.lower() and 'SL_M' not in java and '"SL"' not in java,
    'no cancel endpoint': '/v1/order/cancel' not in java,
    'no modify endpoint': '/v1/order/modify' not in java,
    'no positions endpoint': '/v1/positions' not in java,
    'no holdings endpoint': '/v1/holdings' not in java,
    'one-time LTP endpoint for manual sizing': '/v1/live-data/ltp' in java,
    'order detail only for fill confirmation': '/v1/order/detail/' in java and 'awaitExecution' in java,
    'manual budget slider 0-100k': 'manualBudgetBar.setMax(10)' in main and '* 10000' in main,
    'manual default budget 50000': 'getInt("manual_budget", 50000)' in (root / 'app/src/main/java/com/suhas/multyfideliverybuy/AppPrefs.java').read_text(),
    'official Groww instrument master': 'growwapi-assets.groww.in/instruments/instrument.csv' in instruments,
    'NSE CASH EQ filter': '"NSE"' in instruments and '"CASH"' in instruments and '"EQ"' in instruments,
    'official tick size preserved': 'return v / 100.0' not in instruments,
    'notification listener service': 'BIND_NOTIFICATION_LISTENER_SERVICE' in manifest,
    'read-only user profile auth test': '/v1/user/detail' in java and 'refreshAndTestAuthentication' in java,
    'static public IP detector': 'api4.ipify.org' in network and 'checkip.amazonaws.com' in network,
    'arm requires readiness': 'isReadyForBuy' in main and 'isReadyForBuy' in service,
    'no static IP lookup in notification hot path': 'NetworkCheck' not in service,
}

failed = [name for name, ok in checks.items() if not ok]
for name, ok in checks.items():
    print(('PASS' if ok else 'FAIL') + ' - ' + name)
if failed:
    raise SystemExit('Contract validation failed: ' + ', '.join(failed))
