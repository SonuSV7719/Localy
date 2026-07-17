package com.localy.worker

import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.View
import android.widget.ArrayAdapter
import android.widget.AdapterView
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.LinearLayoutManager
import com.localy.worker.databinding.ActivityChatBinding
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.Call
import org.json.JSONObject

/**
 * Chat with a model served by a Localy PC over the LAN — including a model that
 * is pooled across this phone and other devices. Auto-discovers the PC via
 * mDNS; the user pastes an API key once. Shows live pooled-load progress.
 */
class ChatActivity : AppCompatActivity() {

    private lateinit var binding: ActivityChatBinding
    private val prefs by lazy { ChatPrefs(this) }
    private val discovery by lazy { ServerDiscovery(this) }
    private lateinit var client: LocalyClient

    private val items = mutableListOf<ChatItem>()
    private val adapter = ChatAdapter(items)

    private var discovered: List<ServerDiscovery.Server> = emptyList()
    private var models: List<String> = emptyList()
    private var streamCall: Call? = null

    private val ui = Handler(Looper.getMainLooper())
    private val poolPoll = object : Runnable {
        override fun run() {
            refreshPoolStatus()
            ui.postDelayed(this, 2500)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityChatBinding.inflate(layoutInflater)
        setContentView(binding.root)
        title = "Localy Chat"

        client = LocalyClient(prefs.baseUrl, prefs.apiKey)

        binding.messagesList.layoutManager = LinearLayoutManager(this).apply { stackFromEnd = true }
        binding.messagesList.adapter = adapter

        binding.rescanButton.setOnClickListener { startDiscovery() }
        binding.connectButton.setOnClickListener { onConnectTapped() }
        binding.changeServerButton.setOnClickListener { showConnect() }
        binding.sendButton.setOnClickListener { if (streamCall != null) stopStreaming() else send() }

        binding.serverSpinner.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            override fun onItemSelected(p: AdapterView<*>?, v: View?, pos: Int, id: Long) {
                discovered.getOrNull(pos)?.let { binding.serverUrlInput.setText(it.baseUrl) }
            }
            override fun onNothingSelected(p: AdapterView<*>?) {}
        }

        if (prefs.isConfigured) showChat() else showConnect()
    }

    override fun onDestroy() {
        super.onDestroy()
        discovery.stop()
        ui.removeCallbacks(poolPoll)
        streamCall?.cancel()
    }

    // --- connect / discovery ----------------------------------------------

    private fun showConnect() {
        ui.removeCallbacks(poolPoll)
        binding.chatPanel.visibility = View.GONE
        binding.connectPanel.visibility = View.VISIBLE
        binding.serverUrlInput.setText(prefs.baseUrl)
        binding.apiKeyInput.setText(prefs.apiKey)
        binding.connectError.visibility = View.GONE
        startDiscovery()
    }

    private fun startDiscovery() {
        discovery.start { servers ->
            runOnUiThread {
                discovered = servers
                val labels = servers.map { "${it.name}  (${it.host}:${it.port})" }
                    .ifEmpty { listOf("Searching… tap Rescan if nothing appears") }
                binding.serverSpinner.adapter = ArrayAdapter(
                    this, android.R.layout.simple_spinner_dropdown_item, labels
                )
            }
        }
    }

    private fun onConnectTapped() {
        val url = binding.serverUrlInput.text.toString().trim().removeSuffix("/")
        val key = binding.apiKeyInput.text.toString().trim()
        if (url.isBlank()) { showConnectError("Choose or enter a server address."); return }
        if (key.isBlank()) { showConnectError("Paste an API key (from the PC's API Access tab)."); return }

        binding.connectButton.isEnabled = false
        binding.connectError.visibility = View.GONE
        client.baseUrl = url
        client.apiKey = key

        lifecycleScope.launch {
            val result = withContext(Dispatchers.IO) {
                try {
                    val list = client.listModels() // also validates URL + key
                    Result.success(list)
                } catch (e: Exception) {
                    Result.failure(e)
                }
            }
            binding.connectButton.isEnabled = true
            result.onSuccess { list ->
                prefs.baseUrl = url
                prefs.apiKey = key
                models = list
                showChat()
            }.onFailure { e ->
                showConnectError(e.message ?: "Could not reach the server.")
            }
        }
    }

    private fun showConnectError(msg: String) {
        binding.connectError.text = msg
        binding.connectError.visibility = View.VISIBLE
    }

    // --- chat --------------------------------------------------------------

    private fun showChat() {
        binding.connectPanel.visibility = View.GONE
        binding.chatPanel.visibility = View.VISIBLE
        discovery.stop()
        populateModels()
        ui.post(poolPoll)
    }

    private fun populateModels() {
        // If we don't have models yet (e.g. returning to a saved server), fetch.
        if (models.isEmpty()) {
            lifecycleScope.launch {
                val list = withContext(Dispatchers.IO) {
                    try { client.listModels() } catch (e: Exception) { emptyList() }
                }
                models = list
                bindModelSpinner()
            }
        } else {
            bindModelSpinner()
        }
    }

    private fun bindModelSpinner() {
        val labels = models.ifEmpty { listOf("No models available") }
        binding.modelSpinner.adapter =
            ArrayAdapter(this, android.R.layout.simple_spinner_dropdown_item, labels)
        val idx = models.indexOf(prefs.lastModel)
        if (idx >= 0) binding.modelSpinner.setSelection(idx)
    }

    private fun selectedModel(): String? {
        val pos = binding.modelSpinner.selectedItemPosition
        return models.getOrNull(pos)
    }

    private fun send() {
        val text = binding.input.text.toString().trim()
        val model = selectedModel()
        if (text.isEmpty()) return
        if (model == null) { showConnectError("No model selected."); return }
        prefs.lastModel = model

        items.add(ChatItem("user", text))
        val assistant = ChatItem("assistant", "")
        items.add(assistant)
        val assistantIndex = items.lastIndex
        adapter.notifyItemRangeInserted(assistantIndex - 1, 2)
        scrollToEnd()
        binding.input.setText("")
        setStreaming(true)

        // Full message history for context.
        val history = items.dropLast(1).map { it.role to it.content }

        streamCall = client.streamChat(
            model = model,
            messages = history,
            onToken = { token ->
                runOnUiThread {
                    assistant.content += token
                    adapter.notifyItemChanged(assistantIndex)
                    scrollToEnd()
                }
            },
            onDone = {
                runOnUiThread {
                    if (assistant.content.isEmpty()) assistant.content = "(no response)"
                    adapter.notifyItemChanged(assistantIndex)
                    setStreaming(false)
                }
            },
            onError = { err ->
                runOnUiThread {
                    assistant.content = if (assistant.content.isEmpty()) "⚠ $err" else assistant.content + "\n\n⚠ $err"
                    adapter.notifyItemChanged(assistantIndex)
                    setStreaming(false)
                }
            }
        )
    }

    private fun stopStreaming() {
        streamCall?.cancel()
        streamCall = null
        setStreaming(false)
    }

    private fun setStreaming(on: Boolean) {
        if (!on) streamCall = null
        binding.sendButton.text = if (on) "Stop" else "Send"
        binding.input.isEnabled = !on
    }

    private fun scrollToEnd() {
        binding.messagesList.scrollToPosition(items.size - 1)
    }

    // --- pooled-load progress ---------------------------------------------

    private fun refreshPoolStatus() {
        lifecycleScope.launch {
            val status = withContext(Dispatchers.IO) { client.poolStatus() }
            if (status != null) renderPoolStatus(status)
        }
    }

    private fun renderPoolStatus(status: JSONObject) {
        val loading = status.optJSONObject("loading")
        val active = loading?.optBoolean("active") == true
        val pooledActive = status.optBoolean("pooled_active")
        val nodeCount = status.optInt("node_count", 0)

        if (!active && !(pooledActive && nodeCount > 1)) {
            binding.poolPanel.visibility = View.GONE
            return
        }
        binding.poolPanel.visibility = View.VISIBLE

        if (active && loading != null) {
            val phase = loading.optString("phase", "loading")
            val model = loading.optString("model", "")
            val remote = loading.optInt("remote_count", 0)
            val elapsed = loading.optDouble("elapsed_s", 0.0)
            val eta = if (loading.isNull("eta_s")) null else loading.optDouble("eta_s")
            val pct = if (loading.isNull("percent")) null else loading.optDouble("percent")
            val bytesTotal = if (loading.isNull("bytes_total")) 0L else loading.optLong("bytes_total")
            val bytesSent = if (loading.isNull("bytes_sent")) 0L else loading.optLong("bytes_sent")

            binding.poolTitle.text = "Loading $model across ${nodeCount} device(s) — ${phaseLabel(phase)}"
            binding.poolProgress.isIndeterminate = pct == null
            if (pct != null) binding.poolProgress.progress = pct.toInt()

            val parts = mutableListOf<String>()
            parts.add(if (pct != null) "${pct.toInt()}%" else "working…")
            parts.add("elapsed ${fmtDur(elapsed)}")
            parts.add("ETA ${if (eta != null) fmtDur(eta) else "…"}")
            if (bytesTotal > 0) parts.add("${fmtBytes(bytesSent)} / ${fmtBytes(bytesTotal)} to $remote worker(s)")
            binding.poolStats.text = parts.joinToString("  ·  ")
            binding.poolLog.text = loading.optString("last_log", "")
        } else if (pooledActive) {
            binding.poolTitle.text = "✅ Serving ${status.optString("active_model")} across $nodeCount devices"
            binding.poolProgress.isIndeterminate = false
            binding.poolProgress.progress = 100
            binding.poolStats.text = "This model runs on the pool — your messages use all connected devices."
            binding.poolLog.text = ""
        }
    }

    private fun phaseLabel(phase: String): String = when (phase) {
        "starting" -> "starting coordinator"
        "loading" -> "streaming layers to devices"
        "ready" -> "ready"
        "error" -> "failed"
        else -> "preparing"
    }

    private fun fmtDur(secs: Double?): String {
        if (secs == null) return "—"
        val s = secs.toInt()
        return if (s < 60) "${s}s" else "${s / 60}m ${s % 60}s"
    }

    private fun fmtBytes(b: Long): String {
        if (b <= 0) return "—"
        val gb = b / (1024.0 * 1024 * 1024)
        return if (gb >= 1) String.format("%.2f GB", gb) else String.format("%.0f MB", b / (1024.0 * 1024))
    }
}
