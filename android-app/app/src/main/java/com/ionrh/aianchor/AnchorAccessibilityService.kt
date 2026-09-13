package com.ionrh.aianchor

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.content.Intent
import android.graphics.Path
import android.graphics.Rect
import android.os.Bundle
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
