package com.localy.worker

import android.graphics.Color
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.LinearLayout
import android.widget.TextView
import androidx.recyclerview.widget.RecyclerView

/**
 * Sessions list shown in the chat drawer. Tap a row to open it; tap ⋮ for
 * rename / archive / delete (handled by the callback with the row's anchor view).
 */
class SessionAdapter(
    private val items: MutableList<Conversation>,
    private val onOpen: (Conversation) -> Unit,
    private val onMenu: (Conversation, View) -> Unit,
) : RecyclerView.Adapter<SessionAdapter.VH>() {

    var activeId: String? = null

    class VH(val row: LinearLayout, val title: TextView, val sub: TextView, val menu: TextView) :
        RecyclerView.ViewHolder(row)

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH {
        val ctx = parent.context
        fun dp(v: Int) = (v * ctx.resources.displayMetrics.density).toInt()

        val row = LinearLayout(ctx).apply {
            layoutParams = RecyclerView.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT
            )
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(dp(14), dp(10), dp(8), dp(10))
        }
        val textCol = LinearLayout(ctx).apply {
            orientation = LinearLayout.VERTICAL
            layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
        }
        val title = TextView(ctx).apply {
            setTextColor(Color.parseColor("#E4E4E7")); textSize = 14f; maxLines = 1; isSingleLine = true
        }
        val sub = TextView(ctx).apply {
            setTextColor(Color.parseColor("#71717A")); textSize = 11f; maxLines = 1; isSingleLine = true
        }
        textCol.addView(title); textCol.addView(sub)
        val menu = TextView(ctx).apply {
            text = "⋮"; setTextColor(Color.parseColor("#A1A1AA")); textSize = 20f
            setPadding(dp(10), dp(4), dp(10), dp(4))
        }
        row.addView(textCol); row.addView(menu)
        return VH(row, title, sub, menu)
    }

    override fun getItemCount() = items.size

    override fun onBindViewHolder(holder: VH, position: Int) {
        val c = items[position]
        holder.title.text = c.title
        holder.sub.text = if (c.modelId.isNotBlank()) c.modelId else "no model yet"
        holder.row.setBackgroundColor(
            if (c.id == activeId) Color.parseColor("#1E2233") else Color.TRANSPARENT
        )
        holder.row.setOnClickListener { onOpen(c) }
        holder.menu.setOnClickListener { onMenu(c, holder.menu) }
    }
}
