package com.localy.worker

import android.os.Bundle
import android.view.View
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.recyclerview.widget.LinearLayoutManager
import com.localy.worker.databinding.ActivityCacheBinding
import java.util.concurrent.Executors

/**
 * Storage screen: view and delete cached model weights on this device.
 * Enumeration/deletion run on a background executor so the UI never blocks,
 * and the list is a RecyclerView so huge caches don't OOM or jank.
 */
class CacheActivity : AppCompatActivity() {

    private lateinit var binding: ActivityCacheBinding
    private lateinit var adapter: CacheAdapter
    private val io = Executors.newSingleThreadExecutor()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityCacheBinding.inflate(layoutInflater)
        setContentView(binding.root)

        adapter = CacheAdapter(onSelectionChanged = ::updateActionBar)
        binding.recycler.layoutManager = LinearLayoutManager(this)
        binding.recycler.adapter = adapter
        binding.recycler.setHasFixedSize(true)

        binding.backButton.setOnClickListener { finish() }
        binding.selectAllButton.setOnClickListener { adapter.selectAll() }
        binding.deleteSelectedButton.setOnClickListener { confirmDeleteSelected() }
        binding.clearAllButton.setOnClickListener { confirmClearAll() }

        refresh()
    }

    private fun refresh() {
        binding.progress.visibility = View.VISIBLE
        io.execute {
            val list = CacheManager.list(this)
            val total = CacheManager.totalSize(this)
            runOnUiThread {
                binding.progress.visibility = View.GONE
                adapter.submit(list)
                binding.totalText.text = "%d item(s) · %s total"
                    .format(list.size, CacheManager.humanSize(total))
                binding.emptyState.visibility = if (list.isEmpty()) View.VISIBLE else View.GONE
                binding.recycler.visibility = if (list.isEmpty()) View.GONE else View.VISIBLE
                binding.clearAllButton.isEnabled = list.isNotEmpty()
            }
        }
    }

    private fun updateActionBar() {
        val n = adapter.selectedCount()
        binding.deleteSelectedButton.isEnabled = n > 0
        binding.deleteSelectedButton.text = if (n > 0) "Delete ($n)" else "Delete"
    }

    private fun confirmDeleteSelected() {
        val paths = adapter.selectedPaths()
        if (paths.isEmpty()) return
        AlertDialog.Builder(this)
            .setTitle("Delete ${paths.size} item(s)?")
            .setMessage("This frees space now. Cached weights will be re-streamed from the coordinator next time they're needed.")
            .setPositiveButton("Delete") { _, _ -> doDelete(paths) }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun confirmClearAll() {
        AlertDialog.Builder(this)
            .setTitle("Clear all cached weights?")
            .setMessage("Removes every cached model block on this device.")
            .setPositiveButton("Clear all") { _, _ ->
                binding.progress.visibility = View.VISIBLE
                io.execute {
                    CacheManager.clearAll(this)
                    runOnUiThread { refresh() }
                }
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun doDelete(paths: Set<String>) {
        binding.progress.visibility = View.VISIBLE
        io.execute {
            CacheManager.delete(paths)
            runOnUiThread { refresh() }
        }
    }

    override fun onDestroy() {
        io.shutdown()
        super.onDestroy()
    }
}
