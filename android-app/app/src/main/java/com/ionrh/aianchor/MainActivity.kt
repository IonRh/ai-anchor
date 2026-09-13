package com.ionrh.aianchor

import android.annotation.SuppressLint
import android.app.Activity
import android.app.AlertDialog
import android.content.SharedPreferences
import android.os.Bundle
import android.view.KeyEvent
import android.view.WindowManager
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebResourceError
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.EditText

/**
 * AI 直播助手安卓壳：WebView 加载电脑端服务的手机页（/mobile.html）。
 * 首次启动询问服务器地址并记住；连接失败可重新填写。
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
        if (saved.isNullOrBlank()) askServer(null) else load(saved)
    }

    private fun load(server: String) {
        prefs.edit().putString("server", server).apply()
        web.loadUrl(server.trimEnd('/') + "/mobile.html")
    }

    private fun askServer(message: String?) {
        val input = EditText(this).apply {
            hint = "http://192.168.1.5:8000"
            setSingleLine(true)
            setText(prefs.getString("server", ""))
        }
        AlertDialog.Builder(this)
            .setTitle("服务器地址")
            .setMessage(message ?: "输入电脑端服务地址（手机与电脑需在同一局域网）")
            .setView(input)
            .setCancelable(false)
            .setPositiveButton("连接") { _, _ ->
                val addr = input.text.toString().trim()
                if (addr.startsWith("http")) load(addr) else askServer("地址需要以 http:// 开头")
            }
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
