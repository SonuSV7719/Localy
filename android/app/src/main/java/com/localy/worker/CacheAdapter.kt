package com.localy.worker

import android.text.format.DateUtils
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.CheckBox
import android.widget.TextView
import androidx.recyclerview.widget.RecyclerView

/**
 * RecyclerView adapter for cache entries. RecyclerView recycles views, so this
 * scrolls smoothly and stays memory-flat even with thousands of entries.
 * Supports multi-select for batch delete.
 */
class CacheAdapter(
    private val onSelectionChanged: () -> Unit,
) : RecyclerView.Adapter<CacheAdapter.VH>() {

    private val items = mutableListOf<CacheManager.Entry>()
    private val selected = linkedSetOf<String>()

    fun submit(list: List<CacheManager.Entry>) {
        items.clear()
        items.addAll(list)
        // Drop selections that no longer exist.
        selected.retainAll(items.map { it.path }.toSet())
        notifyDataSetChanged()
        onSelectionChanged()
    }

    fun selectedPaths(): Set<String> = selected.toSet()

    fun selectedCount(): Int = selected.size

    fun selectAll() {
        selected.clear()
        selected.addAll(items.map { it.path })
        notifyDataSetChanged()
        onSelectionChanged()
    }

    fun clearSelection() {
        selected.clear()
        notifyDataSetChanged()
        onSelectionChanged()
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH {
        val v = LayoutInflater.from(parent.context).inflate(R.layout.item_cache, parent, false)
        return VH(v)
    }

    override fun getItemCount(): Int = items.size

    override fun onBindViewHolder(holder: VH, position: Int) {
        val e = items[position]
        holder.name.text = e.name
        holder.meta.text = "%s · %s".format(
            CacheManager.humanSize(e.sizeBytes),
            DateUtils.getRelativeTimeSpanString(e.lastModified)
        )
        holder.check.isChecked = selected.contains(e.path)
        val toggle = {
            if (selected.contains(e.path)) selected.remove(e.path) else selected.add(e.path)
            holder.check.isChecked = selected.contains(e.path)
            onSelectionChanged()
        }
        holder.itemView.setOnClickListener { toggle() }
        holder.check.setOnClickListener { toggle() }
    }

    class VH(v: View) : RecyclerView.ViewHolder(v) {
        val name: TextView = v.findViewById(R.id.itemName)
        val meta: TextView = v.findViewById(R.id.itemMeta)
        val check: CheckBox = v.findViewById(R.id.itemCheck)
    }
}
