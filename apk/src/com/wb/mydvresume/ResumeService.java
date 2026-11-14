package com.wb.mydvresume;

import android.accessibilityservice.AccessibilityService;
import android.accessibilityservice.AccessibilityServiceInfo;
import android.app.ActivityManager;
import android.app.usage.UsageEvents;
import android.app.usage.UsageStats;
import android.app.usage.UsageStatsManager;
import android.content.BroadcastReceiver;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.os.Handler;
import android.os.Looper;
import android.os.PowerManager;
import android.os.SystemClock;
import android.provider.Settings;
import android.util.Log;
import android.view.KeyEvent;
import android.view.accessibility.AccessibilityEvent;

import java.io.BufferedReader;
import java.io.FileReader;
import java.util.HashSet;
import java.util.List;

/**
 * On-TV (PC-free) resume + cold-boot launcher for TCL 75V8L-C3.
 *
 * v2: after fast-standby wake-up, bring the previous app's existing task back
 * to the foreground. Wake detection uses SCREEN_ON/USER_PRESENT, a 2s poll
 * with a suspend-gap check, and service re-bind (TCL does not reliably deliver
 * window events to third-party accessibility services).
 *
 * v3.0/3.1: cold boot (power cut / adb reboot) via boot_id + elapsedRealtime;
 * target from the SYSTEM usage stats; whitelist gate; configurable default;
 * 120s correction window with user-cancel protection.
 *
 * v3.2: standby wake no longer hard-codes myDV (it hijacked whatever app was
 * being watched, e.g. 欧歌影视).
 *
 * v3.3/3.4: "last app" now comes from the system's foreground EVENT stream
 * (last whitelisted ACTIVITY_RESUMED / MOVE_TO_FOREGROUND), not just the
 * coarse UsageStats.getLastTimeUsed() aggregate, which this TCL refreshes when
 * the service itself launches an app and therefore feeds back on itself.
 * Also: a static component table provides explicit launch intents when
 * Android 11 package visibility makes getLaunchIntentForPackage() return null
 * (we deliberately keep <queries> out of the manifest because TCL rejects
 * manifests containing a LAUNCHER category declaration).
 * Plus: each whitelisted app needs TCL's APP_AUTO_START/APP_ASSOC_START=allow
 * (done by boot_target.py --allow-autostart).
 *
 * v3.5: TCL resumes a BACKGROUNDED myDV MediaSession on wake (verified:
 * "player piid:71 state:started" 0.3s after WAKE while myDV was invisible),
 * so switching the foreground to another app left myDV's audio playing
 * underneath. myDV's own PIP_PAUSE receiver is NOT exported (BroadcastQueue
 * "Permission Denial ... is not exported"), and a third-party app cannot
 * control another app's MediaSession, so the reliable fix is the public
 * ActivityManager.killBackgroundProcesses(TARGET) (normal permission).
 * It only kills BACKGROUND processes and is skipped whenever myDV is the
 * intended/foreground app, so the verified myDV resume is unaffected.
 * Configurable via Settings.System "wb_quiet_mydv" (0/off disables).
 *
 * v4.0: REAL fix for "wake lands on the app home page while audio keeps
 * playing". v3.6/v3.10 started an EXPLICIT HomeActivity with NEW_TASK|
 * SINGLE_TOP: because HomeActivity is singleTop and the task top was
 * Detail/PlayActivity, SINGLE_TOP did not match and Android pushed a FRESH
 * HomeActivity instance over the paused page. v3.9 tried implicit MAIN+
 * LAUNCHER instead, but TCL refuses to resolve it (verified even from adb
 * shell). v4.0 uses the combination verified on-device: EXPLICIT component
 * + ACTION_MAIN + CATEGORY_LAUNCHER + NEW_TASK|RESET_TASK_IF_NEEDED|
 * NO_ANIMATION -> "its current task has been brought to the front", the
 * whole task and its pre-standby top Activity are preserved unchanged.
 * All 5 correction starts are kept (they are idempotent and beat TCL
 * pushing HOME 2-3s after SCREEN_ON). Version 3.0 / versionCode 16.
 *
 * v3.10: complete rollback to the v3.6 behaviour (versionCode 15 / 2.4).
 * v3.7-v3.9.1 regressed "pause before standby -> resume on wake": the
 * exported check, the process-level foreground probe and the launcher intent
 * caused the scheduled correction starts to be skipped, while TCL pushes
 * HOME/HomeActivity 2-3s AFTER SCREEN_ON. v3.6 starts the explicit root
 * (NEW_TASK|SINGLE_TOP) at EVERY correction point, which brings the ORIGINAL
 * task (top = paused Detail/Play page) back to the front.
 * No manifest queries, no QUERY_ALL_PACKAGES, no launcher intent here.
 *
 * v3.6: remember the exact top Activity class shown just before standby
 * (SCREEN_OFF commits it synchronously). On wake, try to restore that class
 * with an explicit ComponentName + SINGLE_TOP first, so an existing task is
 * brought back unchanged instead of surfacing the root/home page. If the
 * Activity is not exported (TVBox PlayActivity/DetailActivity are
 * exported=false, singleTask), the SecurityException is logged and the old
 * root-intent path is used. Repeated root starts are skipped once the target
 * is already in front. Configurable via "wb_exact_resume" (0/off disables).
 * Cold-boot logic is deliberately untouched.
 *
 * No HOME/LAUNCHER declaration (TCL signature gate), no BOOT_COMPLETED
 * receiver: system_server re-binds accessibility services after boot.
 */
public class ResumeService extends AccessibilityService {

    private static final String TAG = "MyDvResume";
    private static final String TARGET = "com.github.mytv.dv";
    private static final String HOME = "com.tcl.cyberui";

    private static final String CFG_TARGET = "wb_boot_target";
    private static final String CFG_WHITELIST = "wb_boot_whitelist";
    private static final String CFG_QUIET = "wb_quiet_mydv";
    private static final String CFG_EXACT = "wb_exact_resume";
    private static final String SP_LAST_CLASS = "last_class";
    private static final String SP_LAST_CLASS_PKG = "last_class_pkg";
    private static final String DEFAULT_BOOT_TARGET = "com.github.mytv.dv";
    private static final String[] DEFAULT_WHITELIST = {
            "com.github.mytv.dv",
            "com.ysc.tvbox",
            "com.cctv.yangshipin.app.androidq",
            "uk.cctv6.mytv.legacz",
            "com.tv.qx",
            "app.yecao",
            "com.local.ktv",
            "cn.toside.music.mobile"
    };

    /** Explicit launcher components, used when PackageManager resolution is
     *  blocked by Android 11 package visibility. Read from `aapt badging`. */
    private static final String[][] KNOWN_COMPONENTS = {
            {"app.yecao", "app.yecao/com.apkmarket.tool.activity.HomeActivity"},
            {"cn.toside.music.mobile", "cn.toside.music.mobile/.MainActivity"},
            {"com.android.letv.browser", "com.android.letv.browser/.LoadingActivity"},
            {"com.bbll.fix", "com.bbll.fix/com.xx.blbl.ui.MainActivity"},
            {"com.cctv.yangshipin.app.androidq",
                    "com.cctv.yangshipin.app.androidq/com.github.tvbox.osc.ui.activity.HomeActivity"},
            {"com.example.tvwallpaper", "com.example.tvwallpaper/.MainActivity"},
            {"com.feicui.tvhd", "com.feicui.tvhd/com.dsdqjx.tvhd.activity.StartActivity"},
            {"com.github.mytv.dv", "com.github.mytv.dv/.MainActivity"},
            {"com.huawei.himovceie",
                    "com.huawei.himovceie/com.github.tvbox.osc.ui.activity.HomeActivity"},
            {"com.local.ktv", "com.local.ktv/.MainActivity"},
            {"com.tv.qx", "com.tv.qx/com.tv.core.ui.MainActivity"},
            {"com.ysc.tvbox",
                    "com.ysc.tvbox/com.github.tvbox.osc.ui.activity.HomeActivity"},
            {"uk.cctv6.mytv.legacz",
                    "uk.cctv6.mytv.legacz/top.yogiczy.mytv.legacy.activities.MainActivity"}
    };

    private static final long POLL_MS = 2000L;
    private static final long SUSPEND_GAP_MS = 9000L;
    private static final long WAKE_WINDOW_MS = 15000L;
    private static final long WAKE_DEBOUNCE_MS = 8000L;
    private static final long LAUNCH_DEBOUNCE_MS = 1200L;
    private static final long[] DELAYS = {800L, 2500L, 5000L, 9000L, 13000L};

    private static final long BOOT_WINDOW_MS = 120000L;
    private static final long[] BOOT_DELAYS = {
            1500L, 5000L, 12000L, 25000L, 45000L, 70000L, 95000L
    };

    private final Handler handler = new Handler(Looper.getMainLooper());
    private long wokeAt = 0L;
    private long lastPollAt = 0L;
    private long lastLaunchAt = 0L;
    private boolean lastInteractive = true;
    private boolean receiverRegistered = false;
    private int wakeSeq = 0;
    private String wakeTarget = TARGET;
    private String wakeClass = "";
    private boolean wakeLaunched = false;
    private String lastClass = "";

    private long bootAt = 0L;
    private int bootSeq = 0;
    private boolean bootCancelled = false;
    private String bootTarget = "";
    private String bootReason = "";
    private int bootLaunchCount = 0;
    private String lastApp = "";
    private boolean usageWarned = false;

    private final BroadcastReceiver screenReceiver = new BroadcastReceiver() {
        @Override
        public void onReceive(Context c, Intent i) {
            String a = i.getAction();
            if (Intent.ACTION_SCREEN_OFF.equals(a)) {
                // Best possible moment before standby; commit synchronously.
                recordForeground();
                recordStandbyClass();
                lastInteractive = false;
                Log.i(TAG, "SCREEN_OFF");
            } else if (Intent.ACTION_SCREEN_ON.equals(a)
                    || Intent.ACTION_USER_PRESENT.equals(a)) {
                lastInteractive = true;
                onWake("broadcast:" + a);
            }
        }
    };

    @Override
    public void onServiceConnected() {
        AccessibilityServiceInfo info = new AccessibilityServiceInfo();
        info.eventTypes = AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED
                | AccessibilityEvent.TYPE_WINDOWS_CHANGED;
        info.feedbackType = AccessibilityServiceInfo.FEEDBACK_GENERIC;
        info.notificationTimeout = 50;
        info.flags = AccessibilityServiceInfo.DEFAULT
                | AccessibilityServiceInfo.FLAG_REQUEST_FILTER_KEY_EVENTS;
        setServiceInfo(info);

        if (!receiverRegistered) {
            IntentFilter f = new IntentFilter();
            f.addAction(Intent.ACTION_SCREEN_ON);
            f.addAction(Intent.ACTION_SCREEN_OFF);
            f.addAction(Intent.ACTION_USER_PRESENT);
            registerReceiver(screenReceiver, f);
            receiverRegistered = true;
        }

        SharedPreferences sp = getSharedPreferences("state", MODE_PRIVATE);
        long now = SystemClock.elapsedRealtime();
        long prevBind = sp.getLong("last_bind", 0L);
        String prevBoot = sp.getString("boot_id", "");
        String curBoot = readBootId();
        boolean idChanged = curBoot.length() > 0 && prevBoot.length() > 0
                && !curBoot.equals(prevBoot);
        boolean clockReset = prevBind > 0L && prevBind > now + 1000L;
        boolean coldBoot = prevBind > 0L && (idChanged || clockReset);

        SharedPreferences.Editor ed = sp.edit();
        ed.putLong("last_bind", now);
        if (curBoot.length() > 0) {
            ed.putString("boot_id", curBoot);
        }
        ed.commit();
        lastApp = sp.getString("last_app", "");
        lastClass = sp.getString(SP_LAST_CLASS, "");

        handler.removeCallbacks(pollRunnable);
        lastPollAt = now;
        lastInteractive = true;
        handler.postDelayed(pollRunnable, POLL_MS);

        Log.i(TAG, "service connected v4.0 (task-reuse wake), prevBindGap="
                + (prevBind > 0L ? (now - prevBind) : 0L)
                + "ms, bootId=" + (curBoot.length() > 0 ? curBoot.substring(0, 8) : "n/a")
                + ", coldBoot=" + coldBoot);

        if (coldBoot) {
            onBoot(sp);
        } else {
            if (prevBind > 0L) {
                // Second (or later) bind in the SAME boot = standby wake / rebind.
                onWake("rebind");
            }
            // Keep a local fallback record whenever the service actually runs.
            recordForeground();
        }
    }

    /** Poll fallback: catches fast-standby that skips standard broadcasts. */
    private final Runnable pollRunnable = new Runnable() {
        @Override
        public void run() {
            long now = SystemClock.elapsedRealtime();
            long gap = now - lastPollAt;
            PowerManager pm = (PowerManager) getSystemService(Context.POWER_SERVICE);
            boolean on = (pm == null) || pm.isInteractive();

            if (on && (!lastInteractive || gap > SUSPEND_GAP_MS)) {
                Log.i(TAG, "WAKE by poll, gap=" + gap + "ms, wasOn=" + lastInteractive);
                onWake("poll");
            }
            lastInteractive = on;
            lastPollAt = now;
            handler.postDelayed(this, POLL_MS);
        }
    };

    @Override
    public void onAccessibilityEvent(AccessibilityEvent e) {
        if (e == null || e.getPackageName() == null) {
            return;
        }
        String pkg = e.getPackageName().toString();

        // Cold-boot session: a deliberate user action cancels the correction
        // window; the launcher taking focus is normal boot churn, not a cancel.
        long sinceBoot = bootAt > 0L ? SystemClock.elapsedRealtime() - bootAt : Long.MAX_VALUE;
        if (bootAt > 0L && !bootCancelled && sinceBoot >= 0L && sinceBoot < BOOT_WINDOW_MS) {
            if (HOME.equals(pkg)) {
                Log.i(TAG, "HOME during boot, since=" + sinceBoot + "ms");
                launchBoot(bootSeq);
            } else if (bootTarget.length() > 0 && !pkg.equals(bootTarget)) {
                bootCancelled = true;
                Log.i(TAG, "BOOT cancelled by user opening " + pkg);
            }
        }

        // Standby path: bring the remembered app back when HOME covers it.
        long since = wokeAt > 0L ? SystemClock.elapsedRealtime() - wokeAt : Long.MAX_VALUE;
        if (HOME.equals(pkg) && since >= 0L && since < WAKE_WINDOW_MS) {
            Log.i(TAG, "HOME after wake (event), since=" + since + "ms");
            launch();
        }
    }

    /** Never consume keys; only use them as a "user is in control" signal. */
    @Override
    protected boolean onKeyEvent(KeyEvent event) {
        if (bootAt > 0L && !bootCancelled && event != null
                && event.getAction() == KeyEvent.ACTION_DOWN
                && SystemClock.elapsedRealtime() - bootAt < BOOT_WINDOW_MS) {
            int c = event.getKeyCode();
            if (c == KeyEvent.KEYCODE_HOME || c == KeyEvent.KEYCODE_BACK
                    || c == KeyEvent.KEYCODE_MENU || c == KeyEvent.KEYCODE_DPAD_CENTER
                    || c == KeyEvent.KEYCODE_ENTER) {
                bootCancelled = true;
                Log.i(TAG, "BOOT cancelled by user key " + c);
            }
        }
        return false;
    }

    private void onWake(String source) {
        long now = SystemClock.elapsedRealtime();
        if (now - wokeAt < WAKE_DEBOUNCE_MS) {
            Log.d(TAG, "wake debounced (" + source + ")");
            return;
        }
        wokeAt = now;
        wakeLaunched = false;
        wakeTarget = resolveWakeTarget();
        wakeClass = resolveWakeClass(wakeTarget);
        final int seq = ++wakeSeq;
        Log.i(TAG, "WAKE via " + source + " seq=" + seq + " target=" + wakeTarget
                + " class=" + (wakeClass.length() > 0 ? wakeClass : "n/a"));
        recordForeground();

        // TCL may resume the background myDV player right after wake; start
        // quieting immediately, before the first scheduled launch.
        quietMyDv("wake seq=" + seq, wakeTarget);

        for (long d : DELAYS) {
            handler.postDelayed(new Runnable() {
                @Override
                public void run() {
                    if (seq != wakeSeq) {
                        return;
                    }
                    if (SystemClock.elapsedRealtime() - wokeAt > WAKE_WINDOW_MS) {
                        return;
                    }
                    launch();
                }
            }, d);
        }
        // Tail sweep: some firmware restores media sessions after the last
        // launch. One last kill just outside the correction window.
        handler.postDelayed(new Runnable() {
            @Override
            public void run() {
                if (seq == wakeSeq) {
                    quietMyDv("wake tail", wakeTarget);
                }
            }
        }, WAKE_WINDOW_MS + 2000L);
    }

    /** v3.4: resume the last whitelisted foreground app; else myDV (v2). */
    private String resolveWakeTarget() {
        String p = recentWhitelistedApp(false);
        Intent probe = resolveBootIntent(p);
        Log.i(TAG, "WAKE candidate=" + (p == null ? "" : p)
                + " intent=" + (probe == null ? "null"
                : String.valueOf(probe.getComponent())));
        if (p != null && p.length() > 0 && isAllowed(p) && probe != null) {
            return p;
        }
        return TARGET;
    }

    private void launch() {
        // During a cold-boot session every "bring back" request must honour the
        // chosen boot target instead of the standby target.
        long now = SystemClock.elapsedRealtime();
        if (bootAt > 0L && !bootCancelled && (now - bootAt) < BOOT_WINDOW_MS) {
            launchBoot(bootSeq);
            return;
        }
        if (now - lastLaunchAt < LAUNCH_DEBOUNCE_MS) {
            return;
        }
        lastLaunchAt = now;

        // v3.5: keep myDV's background audio out while another app is resumed.
        quietMyDv("wake launch", wakeTarget);

        String pkg = (wakeTarget.length() > 0) ? wakeTarget : TARGET;

        // v4.0: keep ALL scheduled correction starts. A task-reuse start is
        // idempotent (it only brings the existing task forward; it never
        // creates a new Activity), so repeating it is harmless -- and it is
        // exactly what beats TCL pushing HOME 2-3s AFTER SCREEN_ON. v3.8
        // skipped the later corrections and the TV stayed on the home page.
        if (wakeLaunched && isPkgForeground(pkg)) {
            Log.i(TAG, "repeat correction, " + pkg + " already in front");
        }
        wakeLaunched = true;

        // v4.0: DROP the v3.6 "exact class" attempt. TVBox play/detail pages
        // are exported=false, so it only threw SecurityException on every
        // correction; and if it ever succeeded it would bypass task reuse.
        // Bringing the existing task forward already keeps the exact top page.

        Intent i = resolveBootIntent(pkg);
        if (i == null) {
            pkg = TARGET;
            i = new Intent();
            i.setComponent(new ComponentName(TARGET, TARGET + ".MainActivity"));
        }
        ComponentName cn = i.getComponent();
        try {
            // v4.0: bring the WHOLE existing task back to the front WITHOUT
            // creating a new HomeActivity. An EXPLICIT component avoids TCL's
            // refusal to resolve implicit MAIN/LAUNCHER intents (v3.9 failed
            // there). MAIN + LAUNCHER + RESET_TASK_IF_NEEDED + NEW_TASK makes
            // the system reuse the task and KEEP its top Activity: verified
            // on-device with the launcher in front -> "its current task has
            // been brought to the front", stack unchanged, top still the
            // pre-standby Detail/History page.
            // SINGLE_TOP must NOT be used here: on TVBox shells the top is
            // Detail/PlayActivity, so SINGLE_TOP misses and Android pushes a
            // FRESH HomeActivity on top -- exactly the "wake lands on the app
            // home page, audio keeps playing" bug in v3.6/v3.10.
            // Build a clean Intent so no stale LEANBACK category/flags from
            // getLaunchIntentForPackage() can change the verified behaviour.
            Intent bring = new Intent(Intent.ACTION_MAIN);
            bring.addCategory(Intent.CATEGORY_LAUNCHER);
            if (cn != null) {
                bring.setComponent(cn);
            } else {
                bring.setPackage(pkg);
            }
            bring.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK
                    | Intent.FLAG_ACTIVITY_RESET_TASK_IF_NEEDED
                    | Intent.FLAG_ACTIVITY_NO_ANIMATION);
            startActivity(bring);
            Log.i(TAG, "launched " + pkg + " (task reuse) top=" + wakeClass);
            return;
        } catch (Throwable t) {
            Log.w(TAG, "task-reuse launch failed, fallback: " + t);
        }
        // Fallback: legacy explicit root start (still gets the app in front).
        try {
            i.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK
                    | Intent.FLAG_ACTIVITY_SINGLE_TOP
                    | Intent.FLAG_ACTIVITY_NO_ANIMATION);
            startActivity(i);
            Log.i(TAG, "launched " + pkg + " (legacy fallback)");
        } catch (Throwable t) {
            Log.w(TAG, "launch failed: " + t);
        }
    }

    // ---------------- v3.6: exact standby-screen restore ----------------

    /** Class of the top Activity that was visible just before standby. */
    private String resolveWakeClass(String pkg) {
        SharedPreferences sp = getSharedPreferences("state", MODE_PRIVATE);
        String savedPkg = sp.getString(SP_LAST_CLASS_PKG, "");
        String savedCls = sp.getString(SP_LAST_CLASS, "");
        if (pkg.equals(savedPkg) && savedCls.length() > 0) {
            Log.i(TAG, "WAKE class from standby record: " + savedCls);
            return savedCls;
        }
        String live = lastAllowedForegroundClass();
        if (live.length() > 0) {
            Log.i(TAG, "WAKE class from usage events: " + live);
            return live;
        }
        if (lastClass.length() > 0) {
            Log.i(TAG, "WAKE class from memory: " + lastClass);
            return lastClass;
        }
        Log.i(TAG, "WAKE class unavailable");
        return "";
    }

    /** SCREEN_OFF: commit the exact screen so a fast suspend cannot lose it. */
    private void recordStandbyClass() {
        String[] pair = lastAllowedForegroundPair();
        if (pair[0].length() > 0 && pair[1].length() > 0) {
            SharedPreferences.Editor ed =
                    getSharedPreferences("state", MODE_PRIVATE).edit();
            ed.putString(SP_LAST_CLASS_PKG, pair[0]);
            ed.putString(SP_LAST_CLASS, pair[1]);
            ed.commit();
            lastClass = pair[1];
            Log.i(TAG, "standby class=" + pair[1] + " (" + pair[0] + ")");
        } else {
            Log.i(TAG, "standby class unavailable");
        }
    }

    /** {package, class} of the newest whitelisted ACTIVITY_RESUMED event. */
    private String[] lastAllowedForegroundPair() {
        try {
            UsageStatsManager um = (UsageStatsManager)
                    getSystemService(Context.USAGE_STATS_SERVICE);
            if (um == null) {
                return new String[]{"", ""};
            }
            HashSet<String> allow = allowedSet();
            long now = System.currentTimeMillis();
            UsageEvents events = um.queryEvents(now - 86400000L, now);
            UsageEvents.Event e = new UsageEvents.Event();
            String lastPkg = "";
            String lastCls = "";
            while (events.hasNextEvent()) {
                events.getNextEvent(e);
                if (e.getEventType() == UsageEvents.Event.MOVE_TO_FOREGROUND
                        && e.getPackageName() != null
                        && allow.contains(e.getPackageName())) {
                    lastPkg = e.getPackageName();
                    String c = e.getClassName();
                    lastCls = (c == null) ? "" : c;
                }
            }
            return new String[]{lastPkg, lastCls};
        } catch (Throwable t) {
            Log.w(TAG, "usage class read failed: " + t);
            return new String[]{"", ""};
        }
    }

    private String lastAllowedForegroundClass() {
        return lastAllowedForegroundPair()[1];
    }

    /** True when the newest foreground event in the last 5s belongs to pkg. */
    private boolean isPkgForeground(String pkg) {
        try {
            UsageStatsManager um = (UsageStatsManager)
                    getSystemService(Context.USAGE_STATS_SERVICE);
            if (um == null) {
                return false;
            }
            long now = System.currentTimeMillis();
            UsageEvents events = um.queryEvents(now - 5000L, now);
            UsageEvents.Event e = new UsageEvents.Event();
            String last = "";
            while (events.hasNextEvent()) {
                events.getNextEvent(e);
                if (e.getEventType() == UsageEvents.Event.MOVE_TO_FOREGROUND
                        && e.getPackageName() != null) {
                    last = e.getPackageName();
                }
            }
            return pkg.equals(last);
        } catch (Throwable t) {
            return false;
        }
    }

    private boolean exactEnabled() {
        String cfg = getCfg(CFG_EXACT);
        return cfg == null || !("0".equals(cfg.trim())
                || "off".equalsIgnoreCase(cfg.trim()));
    }

    private String rootClassName(String pkg) {
        Intent i = resolveBootIntent(pkg);
        return (i != null && i.getComponent() != null)
                ? i.getComponent().getClassName() : "";
    }

    private void onBoot(SharedPreferences sp) {
        String cfg = getCfg(CFG_TARGET);
        if (cfg != null && ("off".equalsIgnoreCase(cfg)
                || "none".equalsIgnoreCase(cfg) || "0".equals(cfg))) {
            Log.i(TAG, "BOOT detected but disabled (" + CFG_TARGET + "=" + cfg + ")");
            bootAt = 0L;
            return;
        }

        // Resolve lazily at the first launch (1.5s later): UsageStatsService
        // may not be ready yet when the accessibility service is first bound.
        bootTarget = "";
        bootReason = "pending";

        bootAt = SystemClock.elapsedRealtime();
        bootCancelled = false;
        bootLaunchCount = 0;
        final int seq = ++bootSeq;
        Log.i(TAG, "BOOT detected, resolving target at first launch");

        for (long d : BOOT_DELAYS) {
            handler.postDelayed(new Runnable() {
                @Override
                public void run() {
                    launchBoot(seq);
                }
            }, d);
        }
        handler.postDelayed(new Runnable() {
            @Override
            public void run() {
                if (seq == bootSeq) {
                    Log.i(TAG, "BOOT done, target=" + bootTarget + " reason=" + bootReason
                            + " launches=" + bootLaunchCount
                            + " cancelled=" + bootCancelled);
                }
            }
        }, BOOT_WINDOW_MS + 2000L);
    }

    private void resolveBootTarget() {
        String cfg = getCfg(CFG_TARGET);
        String fallback = (cfg == null || cfg.trim().length() == 0)
                ? DEFAULT_BOOT_TARGET : cfg.trim();
        String candidate = recentWhitelistedApp(true);
        if (candidate != null && candidate.length() > 0 && isAllowed(candidate)) {
            bootTarget = candidate;
            bootReason = "remembered";
        } else {
            bootTarget = fallback;
            bootReason = "fallback";
        }
        Log.i(TAG, "BOOT resolved target=" + bootTarget + " reason=" + bootReason
                + " candidate=" + (candidate == null ? "" : candidate));
    }

    /**
     * Authoritative "last app": the newest whitelisted foreground event from
     * the system UsageEvents stream (persisted in /data, survives power cut).
     * Falls back to the aggregate UsageStats and then to our own record.
     */
    private String recentWhitelistedApp(boolean bootCtx) {
        String tag = bootCtx ? "BOOT" : "WAKE";
        String own = getSharedPreferences("state", MODE_PRIVATE)
                .getString("last_app", "");
        String eventApp = lastAllowedForeground();
        if (eventApp.length() > 0) {
            Log.i(TAG, tag + " foreground event gave " + eventApp);
            return eventApp;
        }
        try {
            UsageStatsManager um = (UsageStatsManager)
                    getSystemService(Context.USAGE_STATS_SERVICE);
            if (um == null) {
                return own;
            }
            long now = System.currentTimeMillis();
            List<UsageStats> stats = um.queryUsageStats(
                    UsageStatsManager.INTERVAL_DAILY, now - 259200000L, now);
            if (stats != null && stats.size() > 0) {
                String best = null;
                long bestTime = 0L;
                for (int k = 0; k < stats.size(); k++) {
                    UsageStats s = stats.get(k);
                    if (s == null || !isAllowed(s.getPackageName())) {
                        continue;
                    }
                    long t = s.getLastTimeUsed();
                    if (t > bestTime) {
                        bestTime = t;
                        best = s.getPackageName();
                    }
                }
                if (best != null) {
                    return best;
                }
            }
            Log.i(TAG, tag + " stats gave no whitelisted app, using own record");
        } catch (Throwable t) {
            Log.w(TAG, tag + " usage read failed: " + t);
        }
        return own;
    }

    /** Last ACTIVITY_RESUMED / MOVE_TO_FOREGROUND event whose package is
     *  whitelisted; launcher/settings/ad events are skipped. */
    private String lastAllowedForeground() {
        try {
            UsageStatsManager um = (UsageStatsManager)
                    getSystemService(Context.USAGE_STATS_SERVICE);
            if (um == null) {
                return "";
            }
            HashSet<String> allow = allowedSet();
            long now = System.currentTimeMillis();
            UsageEvents events = um.queryEvents(now - 86400000L, now);
            UsageEvents.Event e = new UsageEvents.Event();
            String last = "";
            while (events.hasNextEvent()) {
                events.getNextEvent(e);
                // MOVE_TO_FOREGROUND == ACTIVITY_RESUMED == 1 since API 29.
                if (e.getEventType() == UsageEvents.Event.MOVE_TO_FOREGROUND
                        && e.getPackageName() != null
                        && allow.contains(e.getPackageName())) {
                    last = e.getPackageName();
                }
            }
            return last;
        } catch (Throwable t) {
            if (!usageWarned) {
                Log.w(TAG, "usage events error: " + t);
                usageWarned = true;
            }
            return "";
        }
    }

    private void launchBoot(int seq) {
        if (seq != bootSeq || bootAt <= 0L || bootCancelled) {
            return;
        }
        long now = SystemClock.elapsedRealtime();
        long since = now - bootAt;
        if (since > BOOT_WINDOW_MS) {
            return;
        }
        if (now - lastLaunchAt < LAUNCH_DEBOUNCE_MS) {
            return;
        }
        lastLaunchAt = now;

        if (bootTarget.length() == 0) {
            resolveBootTarget();
        }
        Intent i = resolveBootIntent(bootTarget);
        if (i == null && !DEFAULT_BOOT_TARGET.equals(bootTarget)) {
            Log.w(TAG, "boot target not launchable: " + bootTarget + ", fallback");
            bootTarget = DEFAULT_BOOT_TARGET;
            bootReason = "fallback(unlaunchable)";
            i = resolveBootIntent(bootTarget);
        }
        if (i == null) {
            Log.w(TAG, "BOOT launch failed: no intent for " + bootTarget);
            return;
        }
        // v3.5: no stray myDV audio while booting into another app.
        quietMyDv("boot launch", bootTarget);
        try {
            i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK
                    | Intent.FLAG_ACTIVITY_SINGLE_TOP
                    | Intent.FLAG_ACTIVITY_NO_ANIMATION);
            startActivity(i);
            bootLaunchCount++;
            Log.i(TAG, "BOOT launched " + bootTarget + " (" + bootReason + ") seq="
                    + seq + " since=" + since + "ms");
        } catch (Throwable t) {
            Log.w(TAG, "BOOT launch failed: " + t);
        }
    }

    private Intent resolveBootIntent(String pkg) {
        if (pkg == null || pkg.length() == 0) {
            return null;
        }
        PackageManager pm = getPackageManager();
        Intent i = null;
        try {
            i = pm.getLeanbackLaunchIntentForPackage(pkg);
        } catch (Throwable ignored) {
        }
        if (i == null) {
            try {
                i = pm.getLaunchIntentForPackage(pkg);
            } catch (Throwable ignored) {
            }
        }
        if (i == null && TARGET.equals(pkg)) {
            i = new Intent();
            i.setComponent(new ComponentName(TARGET, TARGET + ".MainActivity"));
        }
        if (i == null) {
            // Android 11 package-visibility fallback: explicit component.
            for (int k = 0; k < KNOWN_COMPONENTS.length; k++) {
                if (KNOWN_COMPONENTS[k][0].equals(pkg)) {
                    ComponentName cn = ComponentName.unflattenFromString(
                            KNOWN_COMPONENTS[k][1]);
                    if (cn != null) {
                        i = new Intent();
                        i.setComponent(cn);
                    }
                    break;
                }
            }
        }
        return i;
    }

    /**
     * v3.5: TCL wakes a backgrounded myDV player, leaving its audio running
     * under another app. myDV's PIP_PAUSE receiver is not exported and a
     * third-party app cannot touch another app's MediaSession, so the only
     * reliable public API is killBackgroundProcesses (normal permission).
     * Skipped when myDV is the chosen target, when the user just brought it
     * to the front, or when the config key disables it.
     */
    private void quietMyDv(String reason, String target) {
        String cfg = getCfg(CFG_QUIET);
        if (cfg != null && ("0".equals(cfg.trim())
                || "off".equalsIgnoreCase(cfg.trim()))) {
            return;
        }
        if (target == null || target.length() == 0 || TARGET.equals(target)) {
            return;
        }
        if (isMyDvForeground()) {
            Log.d(TAG, "quiet skipped: myDV is in front (" + reason + ")");
            return;
        }
        try {
            ActivityManager am = (ActivityManager)
                    getSystemService(Context.ACTIVITY_SERVICE);
            if (am != null) {
                am.killBackgroundProcesses(TARGET);
                Log.i(TAG, "quiet myDV background audio (" + reason + ")");
            }
        } catch (Throwable t) {
            Log.w(TAG, "quiet failed (" + reason + "): " + t);
        }
    }

    /** True only if the most recent foreground event (last 5s) is myDV. */
    private boolean isMyDvForeground() {
        try {
            UsageStatsManager um = (UsageStatsManager)
                    getSystemService(Context.USAGE_STATS_SERVICE);
            if (um == null) {
                return false;
            }
            long now = System.currentTimeMillis();
            UsageEvents events = um.queryEvents(now - 5000L, now);
            UsageEvents.Event e = new UsageEvents.Event();
            String last = "";
            while (events.hasNextEvent()) {
                events.getNextEvent(e);
                if (e.getEventType() == UsageEvents.Event.MOVE_TO_FOREGROUND
                        && e.getPackageName() != null) {
                    last = e.getPackageName();
                }
            }
            return TARGET.equals(last);
        } catch (Throwable t) {
            return false;
        }
    }

    /** Write the local fallback record (used when usage events are empty). */
    private void recordForeground() {
        String best = recentWhitelistedApp(false);
        if (best == null || best.length() == 0 || !isAllowed(best)) {
            return;
        }
        if (!best.equals(lastApp)) {
            lastApp = best;
            getSharedPreferences("state", MODE_PRIVATE)
                    .edit().putString("last_app", best).commit();
            Log.i(TAG, "last=" + best);
        }
    }

    private HashSet<String> allowedSet() {
        HashSet<String> set = new HashSet<String>();
        String cfg = getCfg(CFG_WHITELIST);
        if (cfg != null && cfg.trim().length() > 0) {
            for (String s : cfg.split(",")) {
                set.add(s.trim());
            }
        } else {
            for (int k = 0; k < DEFAULT_WHITELIST.length; k++) {
                set.add(DEFAULT_WHITELIST[k]);
            }
        }
        return set;
    }

    private boolean isAllowed(String pkg) {
        return pkg != null && pkg.length() > 0 && allowedSet().contains(pkg);
    }

    private String getCfg(String key) {
        try {
            return Settings.System.getString(getContentResolver(), key);
        } catch (Throwable t) {
            return null;
        }
    }

    private String readBootId() {
        BufferedReader r = null;
        try {
            r = new BufferedReader(new FileReader("/proc/sys/kernel/random/boot_id"));
            String s = r.readLine();
            return s == null ? "" : s.trim();
        } catch (Throwable t) {
            // SELinux may hide /proc for an unprivileged app; clockReset covers it.
            return "";
        } finally {
            if (r != null) {
                try {
                    r.close();
                } catch (Throwable ignored) {
                }
            }
        }
    }

    @Override
    public void onInterrupt() {
    }

    @Override
    public boolean onUnbind(Intent intent) {
        handler.removeCallbacks(pollRunnable);
        if (receiverRegistered) {
            try {
                unregisterReceiver(screenReceiver);
            } catch (Throwable ignored) {
            }
            receiverRegistered = false;
        }
        return super.onUnbind(intent);
    }
}
