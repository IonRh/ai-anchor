package com.ionrh.aianchor

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.content.Intent
import android.graphics.Color
import android.graphics.Path
import android.graphics.Rect
import android.graphics.PixelFormat
import android.graphics.drawable.GradientDrawable
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.Gravity
import android.view.View
import android.view.WindowManager
import android.widget.LinearLayout
import android.widget.TextView
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo

/**
 * 无障碍服务：代表用户在屏幕上执行自动化操作（一键开播 / 点赞 / 发弹幕 / 按文字点击）。
 * 只在 App 内用户主动触发时执行，不做任何后台监听自动化。
 */
class AnchorAccessibilityService : AccessibilityService() {

    companion object {
        const val DOUYIN_PKG = "com.ss.android.ugc.aweme"
        @Volatile
        var instance: AnchorAccessibilityService? = null
        fun isRunning(): Boolean = instance != null
    }

    override fun onServiceConnected() { instance = this }
    override fun onAccessibilityEvent(event: AccessibilityEvent?) {}
    override fun onInterrupt() {}
    override fun onDestroy() { instance = null }

    // ---------- 能力 ----------

    fun launchApp(pkg: String): Boolean {
        val intent = packageManager.getLaunchIntentForPackage(pkg) ?: return false
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        startActivity(intent)
        return true
    }

    fun tapText(text: String, timeoutMs: Long = 8000): Boolean {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            val node = findNodeByText(text)
            if (node != null && tap(node)) return true
            Thread.sleep(400)
        }
        return false
    }

    /** 双击屏幕中央（抖音默认双击点赞） */
    fun like(): Boolean {
        val m = resources.displayMetrics
        val x = m.widthPixels / 2f
        val y = (m.heightPixels / 2.4f)
        val path = Path().apply { moveTo(x, y) }
        fun tapAt(start: Long) = dispatchGesture(
            GestureDescription.Builder()
                .addStroke(GestureDescription.StrokeDescription(path, start, 50))
                .build(), null, null
        )
        tapAt(0)
        Thread.sleep(130)
        tapAt(220)
        return true
    }

    /** 找到输入框填入文字并点发送（直播间评论区） */
    fun sendComment(text: String): Boolean {
        val root = rootInActiveWindow ?: return false
        val edit = findEditText(root) ?: return false
        val args = Bundle().apply {
            putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, text)
        }
        if (!edit.performAction(AccessibilityNodeInfo.ACTION_FOCUS)) return false
        if (!edit.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args)) return false
        Thread.sleep(300)
        for (t in listOf("发送", "发送弹幕")) if (tapText(t, 1500)) return true
        return false
    }

    fun goBack(): Boolean = performGlobalAction(GLOBAL_ACTION_BACK)

    /** 各平台开播脚本：入口文字（依次尝试）→ 开始按钮文字（依次尝试）。文案随版本变化时按需补充。 */
    private val liveScripts = mapOf(
        "douyin" to Script("com.ss.android.ugc.aweme", listOf("开直播"),
            listOf("开始视频直播", "开启视频直播", "开始直播", "开播")),
        "kuaishou" to Script("com.smile.gifmaker", listOf("开直播", "直播"),
            listOf("开始视频直播", "开始直播", "开播")),
        "bilibili" to Script("com.bilibili.app", listOf("开直播", "直播"),
            listOf("开始直播", "开播", "开始视频直播")),
        "taobao" to Script("com.taobao.taobao", listOf("直播"),
            listOf("开始直播", "开播", "开始视频直播")),
        "pinduoduo" to Script("com.xunmeng.pinduoduo", listOf("多多直播", "直播"),
            listOf("开始直播", "开播")),
        "douyin_lite" to Script("com.ss.android.ugc.aweme.lite", listOf("开直播"),
            listOf("开始视频直播", "开启视频直播", "开始直播", "开播")),
    )

    data class Script(val pkg: String, val entries: List<String>, val starts: List<String>)

    /** 多平台一键开播：打开 App → 依次找入口文字点击 → 依次找开始按钮点击 */
    fun startLive(platform: String): Boolean {
        val script = liveScripts[platform] ?: return false
        if (!launchApp(script.pkg)) return false
        Thread.sleep(3500)
        dismissPopups()
        var entered = false
        for (entry in script.entries) {
            if (tapText(entry, 3000)) { entered = true; break }
        }
        if (!entered) return false
        Thread.sleep(2500)
        dismissPopups()
        for (t in script.starts) {
            if (tapText(t, 2500)) return true
        }
        return false
    }

    private fun dismissPopups() {
        listOf("我知道了", "以后再说", "稍后再说", "取消", "同意").forEach { tapText(it, 500) }
    }

    // ---------- 悬浮球 ----------

    private val mainHandler = Handler(Looper.getMainLooper())
    private var ball: View? = null
    private var panel: View? = null
    private val wm: WindowManager by lazy { getSystemService(WINDOW_SERVICE) as WindowManager }
    val isFloatShowing: Boolean get() = ball != null

    private fun dp(v: Int): Int = (v * resources.displayMetrics.density).toInt()

    private fun circleBg(color: Int): GradientDrawable =
        GradientDrawable().apply { shape = GradientDrawable.OVAL; setColor(color) }

    fun showFloat() {
        if (ball != null) return
        mainHandler.post { addBall() }
    }

    fun hideFloat() {
        mainHandler.post {
            ball?.let { try { wm.removeView(it) } catch (_: Exception) {} }
            ball = null
            hidePanel()
        }
    }

    private fun addBall() {
        val size = dp(52)
        val lp = WindowManager.LayoutParams(
            size, size,
            overlayType(),
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE,
            PixelFormat.TRANSLUCENT
        )
        lp.gravity = Gravity.TOP or Gravity.START
        lp.x = dp(12); lp.y = dp(320)

        val tv = TextView(this).apply {
            text = "AI"
            setTextColor(Color.WHITE)
            gravity = Gravity.CENTER
            textSize = 16f
            background = circleBg(0xE6161F33.toInt()).apply {
                setStroke(dp(1), 0xFF4F8CFF.toInt())
            }
        }

        var downX = 0f; var downY = 0f; var lpX = 0; var lpY = 0; var moved = false
        tv.setOnTouchListener { _, e ->
            when (e.action) {
                android.view.MotionEvent.ACTION_DOWN -> {
                    downX = e.rawX; downY = e.rawY; lpX = lp.x; lpY = lp.y; moved = false; true
                }
                android.view.MotionEvent.ACTION_MOVE -> {
                    if (Math.abs(e.rawX - downX) > dp(6) || Math.abs(e.rawY - downY) > dp(6)) moved = true
                    if (moved) {
                        lp.x = lpX + (e.rawX - downX).toInt()
                        lp.y = lpY + (e.rawY - downY).toInt()
                        try { wm.updateViewLayout(tv, lp) } catch (_: Exception) {}
                    }
                    true
                }
                android.view.MotionEvent.ACTION_UP -> {
                    if (!moved) togglePanel()
                    true
                }
                else -> false
            }
        }

        try {
            wm.addView(tv, lp)
            ball = tv
        } catch (_: Exception) {
            ball = null
        }
    }

    private fun togglePanel() {
        if (panel != null) hidePanel() else showPanel()
    }

    private fun hidePanel() {
        panel?.let { try { wm.removeView(it) } catch (_: Exception) {} }
        panel = null
    }

    private fun showPanel() {
        if (ball == null) return
        hidePanel()
        val dp16 = dp(16)
        val lp = WindowManager.LayoutParams(
            WindowManager.LayoutParams.WRAP_CONTENT, WindowManager.LayoutParams.WRAP_CONTENT,
            overlayType(),
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE,
            PixelFormat.TRANSLUCENT
        )
        lp.gravity = Gravity.TOP or Gravity.START
        lp.x = dp(12); lp.y = dp(390)

        val box = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp16, dp(10), dp16, dp(10))
            background = GradientDrawable().apply {
                setColor(0xF0161F33.toInt()); cornerRadius = dp(14).toFloat()
                setStroke(dp(1), 0xFF26304A.toInt())
            }
        }

        fun item(label: String, onClick: () -> Unit) {
            val t = TextView(this@AnchorAccessibilityService).apply {
                text = label
                setTextColor(Color.WHITE)
                textSize = 14f
                setPadding(0, dp(10), 0, dp(10))
                setOnClickListener {
                    hidePanel()
                    Thread { onClick() }.start()
                }
            }
            box.addView(t)
        }

        item("🚀 开播（上次平台）") { startLive(prefsPlatform()) }
        item("❤️ 点赞") { like() }
        item("↩️ 返回") { goBack() }
        item("📱 打开本应用") {
            startActivity(Intent(this, MainActivity::class.java).apply {
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            })
        }
        item("✕ 关闭悬浮球") { hideFloat() }

        try {
            wm.addView(box, lp)
            panel = box
        } catch (_: Exception) {
            panel = null
        }
    }

    private fun prefsPlatform(): String =
        getSharedPreferences("anchor", MODE_PRIVATE).getString("last_platform", "douyin") ?: "douyin"

    private fun overlayType(): Int =
        if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.O)
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
        else
            @Suppress("DEPRECATION") WindowManager.LayoutParams.TYPE_PHONE

    // ---------- 内部 ----------

    private fun findNodeByText(text: String): AccessibilityNodeInfo? {
        val root = rootInActiveWindow ?: return null
        for (n in root.findAccessibilityNodeInfosByText(text)) {
            if (n.isVisibleToUser) return n
        }
        return null
    }

    private fun findEditText(root: AccessibilityNodeInfo): AccessibilityNodeInfo? {
        val stack = ArrayDeque<AccessibilityNodeInfo>()
        stack.add(root)
        while (stack.isNotEmpty()) {
            val n = stack.removeFirst()
            if (n.className?.toString()?.contains("EditText", ignoreCase = true) == true &&
                n.isVisibleToUser) return n
            for (i in 0 until n.childCount) n.getChild(i)?.let { stack.add(it) }
        }
        return null
    }

    private fun tap(node: AccessibilityNodeInfo): Boolean {
        var n: AccessibilityNodeInfo? = node
        var depth = 0
        while (n != null && depth < 6) {
            if (n.isClickable) return n.performAction(AccessibilityNodeInfo.ACTION_CLICK)
            n = n.parent
            depth++
        }
        // 不可点击时用坐标手势点它中心
        val rect = Rect()
        node.getBoundsInScreen(rect)
        if (rect.isEmpty) return false
        val path = Path().apply { moveTo(rect.exactCenterX(), rect.exactCenterY()) }
        return dispatchGesture(
            GestureDescription.Builder()
                .addStroke(GestureDescription.StrokeDescription(path, 0, 50))
                .build(), null, null
        )
    }
}
