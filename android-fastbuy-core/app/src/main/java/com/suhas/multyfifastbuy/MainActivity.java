package com.suhas.multyfifastbuy;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.graphics.Color;
import android.os.Build;
import android.os.Bundle;
import android.provider.Settings;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

public class MainActivity extends Activity implements TradingEngine.UiSink {
    private TextView status;
    private EditText token;
    private Button arm;

    @Override protected void onCreate(Bundle b) {
        super.onCreate(b);
        if (Build.VERSION.SDK_INT >= 33) requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 9);

        ScrollView scroll = new ScrollView(this);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(dp(20), dp(28), dp(20), dp(28));
        root.setBackgroundColor(Color.rgb(9,14,20));
        scroll.addView(root);

        TextView title = text("Multyfi FastBuy Core", 28, true);
        root.addView(title);
        TextView sub = text("Fresh intraday-only engine • no legacy bytecode • no re-entry • no unprotected-fill liquidation", 14, false);
        sub.setTextColor(Color.rgb(140,220,190));
        root.addView(sub, lp(0,12));

        status = text("DISARMED", 15, false);
        status.setPadding(dp(14),dp(14),dp(14),dp(14));
        status.setBackgroundColor(Color.rgb(20,31,39));
        root.addView(status, lp(0,20));

        token = new EditText(this);
        token.setHint("Groww access token (kept only in memory)");
        token.setTextColor(Color.WHITE); token.setHintTextColor(Color.GRAY);
        token.setSingleLine(true);
        token.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
        root.addView(token, lp(0,20));

        Button setToken = button("LOAD TOKEN");
        setToken.setOnClickListener(v -> FastBuyApp.get().engine().setToken(token.getText().toString()));
        root.addView(setToken, lp(0,10));

        Button access = button("OPEN MULTYFI NOTIFICATION ACCESS");
        access.setOnClickListener(v -> startActivity(new Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS)));
        root.addView(access, lp(0,10));

        Button test = button("ROUTING TEST / CACHE GROWW WALLET");
        test.setOnClickListener(v -> FastBuyApp.get().engine().routeTest());
        root.addView(test, lp(0,10));

        arm = button("ARM FASTBUY CORE");
        arm.setOnClickListener(v -> {
            TradingEngine e = FastBuyApp.get().engine();
            if (e.isArmed()) e.disarm(); else e.arm();
            updateArm();
        });
        root.addView(arm, lp(0,10));

        TextView rules = text(
            "LOCKED CORE RULES\n\n" +
            "BUY: Fresh Multyfi Equity Intraday notification → cached wallet → immediate NSE MIS MARKET BUY. No LTP/depth/position request before BUY.\n\n" +
            "HOLD: Missing broker protection only warns; it NEVER causes a sell. No per-stock downside stop. No re-entry.\n\n" +
            "SELL: Multyfi close-early/book-profit → immediate MARKET SELL; Multyfi target → SELL; +0.50% NET adaptive trail; +1.00% NET zero-buffer peak trail; 14:58 IST mandatory close.\n\n" +
            "DAY GUARD: −2.00% GROSS of wallet snapshot is the separate day-level emergency ceiling.\n\n" +
            "MONITOR: Fresh Groww LTP up to ~4×/sec, under REST minute limits. Fast order thread has Android priority.", 14, false);
        rules.setTextColor(Color.LTGRAY);
        root.addView(rules, lp(0,24));

        setContentView(scroll);
        FastBuyApp.get().engine().setUi(this);
        updateArm();
    }

    @Override protected void onResume(){ super.onResume(); FastBuyApp.get().engine().setUi(this); updateArm(); }
    @Override protected void onDestroy(){ FastBuyApp.get().engine().setUi(null); super.onDestroy(); }

    @Override public void onStatus(String s) { runOnUiThread(() -> { status.setText(s); updateArm(); }); }

    private void updateArm(){ if(arm!=null) arm.setText(FastBuyApp.get().engine().isArmed()?"DISARM":"ARM FASTBUY CORE"); }
    private Button button(String s){ Button b=new Button(this); b.setText(s); b.setAllCaps(false); b.setTextSize(15); return b; }
    private TextView text(String s,int size,boolean bold){ TextView t=new TextView(this);t.setText(s);t.setTextColor(Color.WHITE);t.setTextSize(size);t.setGravity(Gravity.START);if(bold)t.setTypeface(null,1);return t; }
    private LinearLayout.LayoutParams lp(int top,int bottom){LinearLayout.LayoutParams p=new LinearLayout.LayoutParams(-1,-2);p.topMargin=dp(top);p.bottomMargin=dp(bottom);return p;}
    private int dp(int n){return Math.round(n*getResources().getDisplayMetrics().density);}
}
