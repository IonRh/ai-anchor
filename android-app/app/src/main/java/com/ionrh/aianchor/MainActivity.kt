package com.ionrh.aianchor

import android.annotation.SuppressLint
import android.app.Activity
import android.app.AlertDialog
import android.app.PictureInPictureParams
import android.content.Intent
import android.content.SharedPreferences
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.util.Rational
import android.view.KeyEvent
import android.view.WindowManager
import android.webkit.JavascriptInterface
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.EditText
import android.widget.Toast

/**
 * AI 直播助手安卓壳：WebView 加载电脑端服务的手机页（/mobile.html）。
 * 首次启动询问服务器地址并记住；连接失败可重新填写。
 * 注入 AndroidBridge 供页面调用无障碍能力（一键开播/点赞/发弹幕/文字点击）。
 */
class MainActivity : Activity() {

    private lateinit var web: WebView
    private lateinit var prefs: SharedPreferences

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // 直播控制场景保持屏幕常亮
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        prefs = getSharedPreferences("anchor", MODE_PRIVATE)

        web = WebView(this)
        setContentView(web)
        web.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            // 远程语音自动播放：不要求用户手势
            mediaPlaybackRequiresUserGesture = false
            cacheMode = WebSettings.LOAD_DEFAULT
        }
        web.addJavascriptInterface(Bridge(), "AndroidBridge")
        web.webChromeClient = WebChromeClient()
        web.webViewClient = object : WebViewClient() {
            override fun onReceivedError(
                view: WebView, request: WebResourceRequest, error: WebResourceError
            ) {
                if (request.isForMainFrame) {
                    askServer("连接失败：请确认服务已启动、地址正确、手机与电脑在同一网络")
                }
            }
        }

        val saved = prefs.getString("server", null)
        if (saved == null) askServer(null) else load(saved)
    }

    /** 页面 ↔ 无障碍服务的桥。方法在桥线程执行，阻塞式返回结果。 */
    inner class Bridge {
        /** 页面从本地 assets 加载，数据请求指向该地址（空 = 离线模式） */
        @JavascriptInterface
        fun serverUrl(): String = prefs.getString("server", "") ?: ""

        @JavascriptInterface
        fun setServer(url: String) {
            prefs.edit().putString("server", url.trim()).apply()
            runOnUiThread { web.loadUrl("file:///android_asset/mobile.html") }
        }

        @JavascriptInterface
        fun serviceEnabled(): Boolean = AnchorAccessibilityService.isRunning()

        @JavascriptInterface
        fun openAccessibilitySettings() {
            runOnUiThread {
                startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))
                Toast.makeText(this@MainActivity, "在列表中找到「AI直播助手」并开启", Toast.LENGTH_LONG).show()
            }
        }

        @JavascriptInterface
        fun startLive(platform: String): Boolean {
            prefs.edit().putString("last_platform", platform).apply()
            return svc()?.startLive(platform) ?: false
        }

        @JavascriptInterface
        fun like(): Boolean = svc()?.like() ?: false

        @JavascriptInterface
        fun sendComment(text: String): Boolean = svc()?.sendComment(text) ?: false

        @JavascriptInterface
        fun tapText(text: String): Boolean = svc()?.tapText(text) ?: false

        @JavascriptInterface
        fun goBack(): Boolean = svc()?.goBack() ?: false

        /** 缩成画中画小窗（悬浮在抖音等应用上，窗口内按钮仍可操作） */
        @JavascriptInterface
        fun enterPip() {
            runOnUiThread { enterPipNow() }
        }

        @JavascriptInterface
        fun setAutoPip(on: Boolean) {
            prefs.edit().putBoolean("auto_pip", on).apply()
        }

        @JavascriptInterface
        fun autoPipEnabled(): Boolean = prefs.getBoolean("auto_pip", true)

        /** 悬浮球：需要系统授予「显示在其他应用上层」权限 */
        @JavascriptInterface
        fun overlayReady(): Boolean = Settings.canDrawOverlays(this@MainActivity)

        @JavascriptInterface
        fun openOverlaySettings() {
            runOnUiThread {
                startActivity(Intent(
                    Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                    android.net.Uri.parse("package:$packageName")
                ))
                Toast.makeText(this, "请允许「显示在其他应用上层」，然后回来重新打开开关", Toast.LENGTH_LONG).show()
            }
        }

        @JavascriptInterface
        fun floatShow() {
            if (!Settings.canDrawOverlays(this@MainActivity)) {
                runOnUiThread { openOverlaySettings() }
                return
            }
            svc()?.showFloat()
        }

        @JavascriptInterface
        fun floatHide() {
            svc()?.hideFloat()
        }

        @JavascriptInterface
        fun floatShowing(): Boolean = svc()?.isFloatShowing ?: false
    }

    /** 离开应用（如去刷抖音）时自动缩成小窗，保持遥控可见 */
    override fun onUserLeaveHint() {
        if (prefs.getBoolean("auto_pip", true)) enterPipNow()
    }

    private fun enterPipNow() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val params = PictureInPictureParams.Builder()
                .setAspectRatio(Rational(9, 16))
                .build()
            enterPictureInPictureMode(params)
        }
    }

    private fun svc(): AnchorAccessibilityService? =
        AnchorAccessibilityService.instance ?: run {
            runOnUiThread {
                Toast.makeText(this, "请先在设置页开启无障碍服务", Toast.LENGTH_SHORT).show()
            }
            null
        }

    private fun load(server: String) {
        prefs.edit().putString("server", server).apply()
        // 界面从 APK 本地 assets 加载（不依赖服务端存活），数据通过 AndroidBridge.serverUrl() 取
        web.loadUrl("file:///android_asset/mobile.html")
    }

    private fun askServer(message: String?) {
        val input = EditText(this).apply {
            hint = "http://192.168.1.5:8000"
            setSingleLine(true)
            setText(prefs.getString("server", ""))
        }
        AlertDialog.Builder(this)
            .setTitle("服务器地址")
            .setMessage(message
                ?: "填电脑端服务地址可远程控制直播（手机与电脑同一局域网）。\n没有服务器？点「离线使用」，仅抖音自动化可用，之后可在设置页补填。")
            .setView(input)
            .setCancelable(false)
            .setPositiveButton("连接") { _, _ ->
                var addr = input.text.toString().trim()
                if (addr.isNotEmpty() && !addr.startsWith("http")) addr = "http://$addr"
                load(addr)
            }
            .setNeutralButton("离线使用") { _, _ -> load("") }
            .show()
    }

    override fun onKeyDown(keyCode: Int, event: KeyEvent?): Boolean {
        if (keyCode == KeyEvent.KEYCODE_BACK && web.canGoBack()) {
            web.goBack()
            return true
        }
        return super.onKeyDown(keyCode, event)
    }
}
