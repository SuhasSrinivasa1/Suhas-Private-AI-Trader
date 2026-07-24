package com.dhruva.multyfibridge;

import android.app.Activity;
import android.content.ComponentName;
import android.content.Intent;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.os.Bundle;
import android.provider.Settings;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.CompoundButton;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.Switch;
import android.widget.TextView;
import android.widget.Toast;
import java.util.Locale;

public class MainActivity extends Activity {
    private static final int BG = Color.rgb(8, 17, 31);
    private static final int CARD = Color.rgb(18, 31, 49);
    private static final int TEXT = Color.rgb(242, 247, 255);
    private static final int MUTED = Color.rgb(157, 174, 196);
    private static final int TEAL = Color.rgb(33, 212, 180);
    private static final int BLUE = Color.rgb(90, 124, 255);
    private static final int RED = Color.rgb(255, 100, 116);

    private Switch armedSwitch;
    private TextView accessStatus;
    private TextView logsView;
    private EditText gatewayInput;
    private EditText tokenInput;
    private EditText packageInput;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().setStatusBarColor(BG);
        getWindow().setNavigationBarColor(BG);
        setContentView(buildUi());
    }

    @Override protected void onResume() {
        super.onResume();
        refreshStatus();
    }

    private View buildUi() {
        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        scroll.setBackgroundColor(BG);
        LinearLayout root = vertical();
        root.setPadding(dp(18), dp(22), dp(18), dp(32));
        scroll.addView(root, new ScrollView.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        TextView eyebrow = label("DHRUVA MARKET INTELLIGENCE", 12, TEAL, true);
        eyebrow.setLetterSpacing(0.12f);
        root.addView(eyebrow);
        TextView title = label("Multyfi Auto-Buy Bridge", 28, TEXT, true);
        title.setPadding(0, dp(6), 0, dp(4));
        root.addView(title);
        root.addView(label("Android notification → Dhruva gateway → Groww GTT BUY", 14, MUTED, false));
        addGap(root);
        root.addView(statusCard()); addGap(root);
        root.addView(rulesCard()); addGap(root);
        root.addView(configCard()); addGap(root);
        root.addView(testCard()); addGap(root);
        root.addView(logCard());
        TextView footer = label("v1.0.0 • Groww credentials are never stored in this APK.", 12, MUTED, false);
        footer.setPadding(0, dp(18), 0, 0);
        root.addView(footer);
        return scroll;
    }

    private View statusCard() {
        LinearLayout card = card();
        card.addView(sectionTitle("AUTOMATION STATUS"));
        LinearLayout row = horizontal();
        LinearLayout copy = vertical();
        copy.addView(label("Live automatic GTT buying", 17, TEXT, true));
        copy.addView(label("Master kill switch. OFF by default.", 13, MUTED, false));
        row.addView(copy, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
        armedSwitch = new Switch(this);
        armedSwitch.setChecked(BridgeStore.isArmed(this));
        armedSwitch.setOnCheckedChangeListener(new CompoundButton.OnCheckedChangeListener() {
            @Override public void onCheckedChanged(CompoundButton button, boolean checked) {
                if (checked && (!hasNotificationAccess() || BridgeStore.gatewayUrl(MainActivity.this).isEmpty())) {
                    button.setChecked(false);
                    toast("Grant notification access and save the gateway URL first.");
                    return;
                }
                BridgeStore.setArmed(MainActivity.this, checked);
                BridgeStore.addLog(MainActivity.this, checked ? "ARMED" : "DISARMED",
                        checked ? "Automatic Multyfi GTT BUY forwarding enabled." : "Automatic forwarding disabled.");
                refreshLogs();
            }
        });
        row.addView(armedSwitch);
        card.addView(row);
        accessStatus = label("", 14, MUTED, false);
        accessStatus.setPadding(0, dp(14), 0, 0);
        card.addView(accessStatus);
        Button access = button("Open Notification Access", BLUE);
        access.setOnClickListener(v -> {
            try { startActivity(new Intent("android.settings.ACTION_NOTIFICATION_LISTENER_SETTINGS")); }
            catch (Exception e) { startActivity(new Intent(Settings.ACTION_SETTINGS)); }
        });
        card.addView(access, buttonParams());
        return card;
    }

    private View rulesCard() {
        LinearLayout card = card();
        card.addView(sectionTitle("LOCKED ORDER RULES"));
        card.addView(rule("Order", "Groww GTT BUY"));
        card.addView(rule("Quantity", "100 shares"));
        card.addView(rule("Entry reference", "Upper Multyfi entry price"));
        card.addView(rule("Maximum buy cap", "Entry high + up to 1.00%"));
        card.addView(rule("Exchange / product", "NSE CASH • CNC Delivery"));
        card.addView(rule("Target / SL / sell", "Never created"));
        return card;
    }

    private View configCard() {
        LinearLayout card = card();
        card.addView(sectionTitle("DHRUVA GATEWAY"));
        card.addView(label("Enter your secured Dhruva execution endpoint. Do not enter Groww credentials.", 13, MUTED, false));
        gatewayInput = input("Gateway order endpoint", BridgeStore.gatewayUrl(this), InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        tokenInput = input("Bridge API token", BridgeStore.apiToken(this), InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
        packageInput = input("Multyfi package override (optional)", BridgeStore.sourcePackage(this), InputType.TYPE_CLASS_TEXT);
        card.addView(gatewayInput, fieldParams());
        card.addView(tokenInput, fieldParams());
        card.addView(packageInput, fieldParams());
        card.addView(label("Leave package blank for app-label auto-detection. Set the exact package later for stronger source verification.", 12, MUTED, false));

        Button save = button("Save Configuration", TEAL);
        save.setTextColor(BG);
        save.setOnClickListener(v -> {
            BridgeStore.saveConfig(this, gatewayInput.getText().toString(), tokenInput.getText().toString(), packageInput.getText().toString());
            toast("Configuration saved locally.");
            refreshStatus();
        });
        card.addView(save, buttonParams());

        Button test = button("Test Gateway Connection", BLUE);
        test.setOnClickListener(v -> {
            BridgeStore.saveConfig(this, gatewayInput.getText().toString(), tokenInput.getText().toString(), packageInput.getText().toString());
            test.setEnabled(false); test.setText("Testing…");
            BridgeClient.test(gatewayInput.getText().toString(), tokenInput.getText().toString(), (ok, message) -> runOnUiThread(() -> {
                test.setEnabled(true); test.setText("Test Gateway Connection");
                BridgeStore.addLog(this, ok ? "GATEWAY OK" : "GATEWAY FAILED", message);
                toast(message); refreshLogs();
            }));
        });
        card.addView(test, buttonParams());
        return card;
    }

    private View testCard() {
        LinearLayout card = card();
        card.addView(sectionTitle("PARSER TEST"));
        card.addView(label("Parses the supplied sample locally and never sends an order.", 13, MUTED, false));
        Button sample = button("Parse Sample: SGFIN ₹681–₹684", BLUE);
        sample.setOnClickListener(v -> {
            String raw = "Today's Free Equity Recommendation\nStock Name : SGFIN\nTarget: ₹700\nEntry Range: ₹681-684\nStop Loss: ₹676";
            SignalParser.ParsedSignal s = SignalParser.parse(raw, System.currentTimeMillis());
            if (s == null) { toast("Parser test failed."); return; }
            String message = s.symbol + " • GTT BUY • Qty 100 • Entry high ₹" + money(s.entryHigh)
                    + " • Max cap ₹" + money(s.maxBuyPrice) + " • Target/SL ignored";
            BridgeStore.addLog(this, "TEST PARSED", message);
            toast(message); refreshLogs();
        });
        card.addView(sample, buttonParams());
        return card;
    }

    private View logCard() {
        LinearLayout card = card();
        LinearLayout header = horizontal();
        header.addView(sectionTitle("LOCAL EVENT LOG"), new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
        Button clear = button("Clear", RED);
        clear.setTextSize(12);
        clear.setOnClickListener(v -> { BridgeStore.clearLogs(this); refreshLogs(); });
        header.addView(clear, new LinearLayout.LayoutParams(dp(88), dp(42)));
        card.addView(header);
        logsView = label(BridgeStore.formattedLogs(this), 12, TEXT, false);
        logsView.setTypeface(Typeface.MONOSPACE);
        logsView.setTextIsSelectable(true);
        card.addView(logsView);
        return card;
    }

    private View rule(String key, String value) {
        LinearLayout row = horizontal(); row.setPadding(0, dp(8), 0, dp(8));
        row.addView(label(key, 13, MUTED, false), new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, .46f));
        TextView val = label(value, 14, TEXT, true); val.setGravity(Gravity.END);
        row.addView(val, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, .54f));
        return row;
    }

    private void refreshStatus() {
        boolean access = hasNotificationAccess();
        if (accessStatus != null) {
            accessStatus.setText(access ? "● Notification access granted — listener ready." : "● Notification access required.");
            accessStatus.setTextColor(access ? TEAL : RED);
        }
        refreshLogs();
    }

    private boolean hasNotificationAccess() {
        String enabled = Settings.Secure.getString(getContentResolver(), "enabled_notification_listeners");
        String component = new ComponentName(this, MultyfiNotificationService.class).flattenToString();
        return enabled != null && enabled.contains(component);
    }

    private void refreshLogs() { if (logsView != null) logsView.setText(BridgeStore.formattedLogs(this)); }
    private void addGap(LinearLayout root) { View gap = new View(this); root.addView(gap, new LinearLayout.LayoutParams(1, dp(14))); }

    private LinearLayout card() {
        LinearLayout card = vertical(); card.setPadding(dp(16), dp(16), dp(16), dp(16));
        GradientDrawable bg = new GradientDrawable(); bg.setColor(CARD); bg.setCornerRadius(dp(18)); bg.setStroke(dp(1), Color.rgb(36,55,78));
        card.setBackground(bg); return card;
    }

    private TextView sectionTitle(String text) {
        TextView view = label(text, 12, TEAL, true); view.setLetterSpacing(.1f); view.setPadding(0,0,0,dp(12)); return view;
    }

    private EditText input(String hint, String value, int type) {
        EditText edit = new EditText(this); edit.setHint(hint); edit.setHintTextColor(Color.rgb(112,133,159));
        edit.setTextColor(TEXT); edit.setText(value); edit.setTextSize(14); edit.setSingleLine(true); edit.setInputType(type); edit.setPadding(dp(14),0,dp(14),0);
        GradientDrawable bg = new GradientDrawable(); bg.setColor(Color.rgb(11,23,38)); bg.setCornerRadius(dp(12)); bg.setStroke(dp(1),Color.rgb(48,68,94));
        edit.setBackground(bg); return edit;
    }

    private Button button(String text, int color) {
        Button b = new Button(this); b.setText(text); b.setTextColor(Color.WHITE); b.setTextSize(14); b.setAllCaps(false); b.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        GradientDrawable bg = new GradientDrawable(); bg.setColor(color); bg.setCornerRadius(dp(12)); b.setBackground(bg); return b;
    }

    private TextView label(String text, int sp, int color, boolean bold) {
        TextView v = new TextView(this); v.setText(text); v.setTextSize(sp); v.setTextColor(color); v.setLineSpacing(0,1.12f);
        if (bold) v.setTypeface(Typeface.DEFAULT, Typeface.BOLD); return v;
    }

    private LinearLayout vertical() { LinearLayout l = new LinearLayout(this); l.setOrientation(LinearLayout.VERTICAL); return l; }
    private LinearLayout horizontal() { LinearLayout l = new LinearLayout(this); l.setOrientation(LinearLayout.HORIZONTAL); l.setGravity(Gravity.CENTER_VERTICAL); return l; }
    private LinearLayout.LayoutParams fieldParams() { LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(54)); p.topMargin=dp(10); return p; }
    private LinearLayout.LayoutParams buttonParams() { LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(50)); p.topMargin=dp(12); return p; }
    private int dp(int v) { return Math.round(v * getResources().getDisplayMetrics().density); }
    private void toast(String m) { Toast.makeText(this, m, Toast.LENGTH_LONG).show(); }
    private static String money(double v) { return Math.rint(v)==v ? String.format(Locale.US,"%.0f",v) : String.format(Locale.US,"%.2f",v); }
}
