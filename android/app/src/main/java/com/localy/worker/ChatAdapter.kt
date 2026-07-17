package com.localy.worker

import android.graphics.Color
import android.graphics.Typeface
import android.view.Gravity
import android.view.ViewGroup
import android.widget.LinearLayout
import android.widget.TextView
import androidx.recyclerview.widget.RecyclerView

/** A single chat turn. `content` is mutable so we can append streaming tokens. */
data class ChatItem(val role: String, var content: String)

/**
 * Renders chat messages as aligned bubbles: user on the right, assistant on the
 * left. Assistant reasoning wrapped in <think>…</think> is stripped from the
 * shown text (kept simple on mobile — the final answer is what matters here).
 */
class ChatAdapter(private val items: MutableList<ChatItem>) :
    RecyclerView.Adapter<ChatAdapter.VH>() {

    class VH(val row: LinearLayout, val bubble: TextView) : RecyclerView.ViewHolder(row)

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH {
        val ctx = parent.context
        val row = LinearLayout(ctx).apply {
            layoutParams = RecyclerView.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT
            )
            orientation = LinearLayout.HORIZONTAL
            val pad = dp(ctx, 6)
            setPadding(dp(ctx, 12), pad, dp(ctx, 12), pad)
        }
        val bubble = TextView(ctx).apply {
            setTextColor(Color.WHITE)
            textSize = 15f
            setPadding(dp(ctx, 14), dp(ctx, 10), dp(ctx, 14), dp(ctx, 10))
            setTextIsSelectable(true)
        }
        row.addView(bubble)
        return VH(row, bubble)
    }

    override fun getItemCount(): Int = items.size

    override fun onBindViewHolder(holder: VH, position: Int) {
        val item = items[position]
        val isUser = item.role == "user"
        val ctx = holder.row.context

        holder.bubble.text = displayText(item)
        holder.bubble.setBackgroundColor(if (isUser) 0xFF6366F1.toInt() else 0xFF1F2430.toInt())
        holder.bubble.setTypeface(null, if (item.content.isEmpty()) Typeface.ITALIC else Typeface.NORMAL)

        val lp = LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.WRAP_CONTENT,
            LinearLayout.LayoutParams.WRAP_CONTENT
        )
        lp.setMargins(if (isUser) dp(ctx, 48) else 0, 0, if (isUser) 0 else dp(ctx, 48), 0)
        holder.bubble.layoutParams = lp
        holder.row.gravity = if (isUser) Gravity.END else Gravity.START
    }

    private fun displayText(item: ChatItem): String {
        if (item.role == "user") {
            val idx = item.content.indexOf(ATTACH_DELIM)
            if (idx == -1) return item.content
            val text = item.content.substring(0, idx).trim()
            val blob = item.content.substring(idx + ATTACH_DELIM.length)
            val files = Regex("\\[file: (.+?)\\]").findAll(blob).map { it.groupValues[1] }.toList()
            val chips = files.joinToString("  ") { "📎 $it" }
            return if (text.isEmpty()) chips else "$chips\n$text"
        }
        if (item.content.isEmpty()) return "…"
        // Drop reasoning blocks; show the final answer.
        val cleaned = item.content
            .replace(Regex("(?s)<think(?:ing)?>.*?</think(?:ing)?>"), "")
            .replace(Regex("(?s)<think(?:ing)?>.*$"), "") // still-open reasoning
            .trim()
        return cleaned.ifEmpty { "Thinking…" }
    }

    private fun dp(ctx: android.content.Context, v: Int): Int =
        (v * ctx.resources.displayMetrics.density).toInt()

    companion object {
        // Must match the delimiter ChatActivity uses to append document context.
        const val ATTACH_DELIM = "\n\n===LOCALY_ATTACHMENTS===\n"
    }
}
