package com.localy.worker

import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.OpenableColumns
import android.view.View
import android.widget.ArrayAdapter
import android.widget.AdapterView
import android.widget.EditText
import android.widget.PopupMenu
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AlertDialog
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
 * Chat with a model served by a Localy PC over the LAN, with on-device chat
 * sessions (SQLite), document attachments, streaming, and live pooled-load
 * progress. All chat history is stored locally on the phone.
 */
class ChatActivity : AppCompatActivity() {

    private lateinit var binding: ActivityChatBinding
    private val prefs by lazy { ChatPrefs(this) }
    private val db by lazy { ChatDb(this) }
    private val discovery by lazy { ServerDiscovery(this) }
    private lateinit var client: LocalyClient

    // Current conversation
    private var currentId: String? = null
    private val items = mutableListOf<ChatItem>()
    private val adapter = ChatAdapter(items)

    // Sessions drawer
    private val sessions = mutableListOf<Conversation>()
    private lateinit var sessionAdapter: SessionAdapter
    private var showingArchived = false

    // Staged document attachments (name -> extracted text)
    private val attachments = mutableListOf<Pair<String, String>>()
    // Staged images (name -> base64 data URL); usable only with vision models.
    private val stagedImages = mutableListOf<Pair<String, String>>()
    private var visionIds: Set<String> = emptySet()

    private var discovered: List<ServerDiscovery.Server> = emptyList()
    private var models: List<String> = emptyList()
    private var streamCall: Call? = null
    // Bumped whenever a stream is superseded (session switch / new chat / stop),
    // so late callbacks from an old stream can't corrupt the current chat.
    private var streamGen = 0

    private val ui = Handler(Looper.getMainLooper())
    private val poolPoll = object : Runnable {
        override fun run() {
            refreshPoolStatus()
            ui.postDelayed(this, 2500)
        }
    }

    private val pickFiles =
        registerForActivityResult(ActivityResultContracts.GetMultipleContents()) { uris ->
            if (!uris.isNullOrEmpty()) extractFiles(uris)
        }

    private val pickImages =
        registerForActivityResult(ActivityResultContracts.GetMultipleContents()) { uris ->
            if (!uris.isNullOrEmpty()) encodeImages(uris)
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityChatBinding.inflate(layoutInflater)
        setContentView(binding.root)
        title = "Localy Chat"

        client = LocalyClient(prefs.baseUrl, prefs.apiKey)

        binding.messagesList.layoutManager = LinearLayoutManager(this).apply { stackFromEnd = true }
        binding.messagesList.adapter = adapter

        sessionAdapter = SessionAdapter(sessions, ::openConversation, ::showSessionMenu)
        binding.sessionsList.layoutManager = LinearLayoutManager(this)
        binding.sessionsList.adapter = sessionAdapter

        binding.rescanButton.setOnClickListener { startDiscovery() }
        binding.connectButton.setOnClickListener { onConnectTapped() }
        binding.changeServerButton.setOnClickListener { showConnect() }
        binding.sendButton.setOnClickListener { if (streamCall != null) stopStreaming() else send() }
        binding.menuButton.setOnClickListener { binding.drawer.openDrawer(binding.sessionDrawer) }
        binding.newChatButton.setOnClickListener { newChat() }
        binding.tabActive.setOnClickListener { showingArchived = false; loadSessions() }
        binding.tabArchived.setOnClickListener { showingArchived = true; loadSessions() }
        binding.attachButton.setOnClickListener { pickFiles.launch("*/*") }
        binding.imageButton.setOnClickListener { pickImages.launch("image/*") }
        binding.attachmentClear.setOnClickListener {
            attachments.clear(); stagedImages.clear(); renderAttachments()
        }

        binding.serverSpinner.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            override fun onItemSelected(p: AdapterView<*>?, v: View?, pos: Int, id: Long) {
                discovered.getOrNull(pos)?.let { binding.serverUrlInput.setText(it.baseUrl) }
            }
            override fun onNothingSelected(p: AdapterView<*>?) {}
        }
        binding.modelSpinner.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            override fun onItemSelected(p: AdapterView<*>?, v: View?, pos: Int, id: Long) { updateImageButton() }
            override fun onNothingSelected(p: AdapterView<*>?) {}
        }

        if (prefs.isConfigured) showChat() else showConnect()
    }

    override fun onDestroy() {
        super.onDestroy()
        discovery.stop()
        ui.removeCallbacks(poolPoll)
        cancelActiveStream()
        saveCurrentBlocking()
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
                try { Result.success(client.listModels()) } catch (e: Exception) { Result.failure(e) }
            }
            binding.connectButton.isEnabled = true
            result.onSuccess { list ->
                prefs.baseUrl = url; prefs.apiKey = key; models = list
                showChat()
            }.onFailure { e -> showConnectError(e.message ?: "Could not reach the server.") }
        }
    }

    private fun showConnectError(msg: String) {
        binding.connectError.text = msg
        binding.connectError.visibility = View.VISIBLE
    }

    // --- sessions ----------------------------------------------------------

    private fun showChat() {
        binding.connectPanel.visibility = View.GONE
        binding.chatPanel.visibility = View.VISIBLE
        discovery.stop()
        populateModels()
        ui.post(poolPoll)

        loadSessions()
        lifecycleScope.launch {
            val first = withContext(Dispatchers.IO) { db.conversations(false).firstOrNull() }
            if (first != null) openConversation(first) else newChat()
        }
    }

    // All DB access runs on Dispatchers.IO — SQLite on the UI thread ANRs on
    // long conversations (saveMessages rewrites every row).
    private fun loadSessions() {
        lifecycleScope.launch {
            val list = withContext(Dispatchers.IO) { db.conversations(showingArchived) }
            sessions.clear(); sessions.addAll(list)
            sessionAdapter.activeId = currentId
            sessionAdapter.notifyDataSetChanged()
            binding.sessionsEmpty.visibility = if (sessions.isEmpty()) View.VISIBLE else View.GONE
            binding.sessionsEmpty.text = if (showingArchived) "No archived chats." else "No chats yet."
        }
    }

    private fun newChat() {
        cancelActiveStream()
        saveCurrent()
        val id = System.currentTimeMillis().toString() + "-" + (0..9999).random()
        val model = selectedModel().orEmpty()
        currentId = id
        items.clear()
        attachments.clear(); stagedImages.clear(); renderAttachments()
        adapter.notifyDataSetChanged()
        setStreaming(false)
        showingArchived = false
        lifecycleScope.launch {
            withContext(Dispatchers.IO) { db.createConversation(id, "New chat", model, System.currentTimeMillis()) }
            loadSessions()
        }
        binding.drawer.closeDrawer(binding.sessionDrawer)
    }

    private fun openConversation(conv: Conversation) {
        cancelActiveStream()
        if (conv.id != currentId) saveCurrent()
        currentId = conv.id
        setStreaming(false)
        attachments.clear(); stagedImages.clear(); renderAttachments()
        if (conv.modelId.isNotBlank()) {
            val idx = models.indexOf(conv.modelId)
            if (idx >= 0) binding.modelSpinner.setSelection(idx)
        }
        sessionAdapter.activeId = currentId
        sessionAdapter.notifyDataSetChanged()
        binding.drawer.closeDrawer(binding.sessionDrawer)
        lifecycleScope.launch {
            val msgs = withContext(Dispatchers.IO) { db.messages(conv.id) }
            items.clear(); items.addAll(msgs)
            adapter.notifyDataSetChanged(); scrollToEnd()
        }
    }

    /** Invalidate + cancel any in-flight stream so its callbacks can't write to
     *  or corrupt a different conversation after a switch. */
    private fun cancelActiveStream() {
        if (streamCall != null) {
            streamGen++
            streamCall?.cancel()
            streamCall = null
        }
    }

    /** Persist the current conversation off the UI thread (snapshot + IO). */
    private fun saveCurrent() {
        val id = currentId ?: return
        val snapshot = items.toList()
        val title = deriveTitle()
        val model = selectedModel().orEmpty()
        val ts = System.currentTimeMillis()
        lifecycleScope.launch(Dispatchers.IO) {
            db.saveMessages(id, snapshot); db.updateMeta(id, title, model, ts)
        }
    }

    /** Synchronous save for onDestroy, when the lifecycle scope is gone. */
    private fun saveCurrentBlocking() {
        val id = currentId ?: return
        try {
            db.saveMessages(id, items.toList())
            db.updateMeta(id, deriveTitle(), selectedModel().orEmpty(), System.currentTimeMillis())
        } catch (_: Exception) { /* closing */ }
    }

    private fun deriveTitle(): String {
        val firstUser = items.firstOrNull { it.role == "user" }?.content ?: return "New chat"
        val text = firstUser.substringBefore(ChatAdapter.ATTACH_DELIM).trim().ifBlank { "Attachment chat" }
        return if (text.length > 40) text.take(40) + "…" else text
    }

    private fun showSessionMenu(conv: Conversation, anchor: View) {
        val menu = PopupMenu(this, anchor)
        menu.menu.add("Rename")
        menu.menu.add(if (conv.archived) "Unarchive" else "Archive")
        menu.menu.add("Delete")
        menu.setOnMenuItemClickListener { mi ->
            when (mi.title.toString()) {
                "Rename" -> promptRename(conv)
                "Archive", "Unarchive" -> {
                    db.setArchived(conv.id, !conv.archived)
                    if (conv.id == currentId && !conv.archived) currentId = null
                    loadSessions()
                    ensureOpenConversation()
                }
                "Delete" -> confirmDelete(conv)
            }
            true
        }
        menu.show()
    }

    private fun promptRename(conv: Conversation) {
        val input = EditText(this).apply { setText(conv.title) }
        AlertDialog.Builder(this)
            .setTitle("Rename chat")
            .setView(input)
            .setPositiveButton("Save") { _, _ ->
                val t = input.text.toString().trim()
                if (t.isNotEmpty()) { db.rename(conv.id, t); loadSessions() }
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun confirmDelete(conv: Conversation) {
        AlertDialog.Builder(this)
            .setTitle("Delete chat?")
            .setMessage("“${conv.title}” will be permanently deleted from this device.")
            .setPositiveButton("Delete") { _, _ ->
                db.deleteConversation(conv.id)
                if (conv.id == currentId) currentId = null
                loadSessions()
                ensureOpenConversation()
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    /** If the current conversation was archived/deleted, open another or start fresh. */
    private fun ensureOpenConversation() {
        if (currentId != null) return
        val next = db.conversations(false).firstOrNull()
        if (next != null) openConversation(next) else newChat()
    }

    // --- models ------------------------------------------------------------

    private fun populateModels() {
        lifecycleScope.launch {
            if (models.isEmpty()) {
                models = withContext(Dispatchers.IO) {
                    try { client.listModels() } catch (e: Exception) { emptyList() }
                }
            }
            visionIds = withContext(Dispatchers.IO) { client.visionModelIds() }
            bindModelSpinner()
        }
    }

    private fun bindModelSpinner() {
        val labels = models.ifEmpty { listOf("No models available") }
        binding.modelSpinner.adapter =
            ArrayAdapter(this, android.R.layout.simple_spinner_dropdown_item, labels)
        updateImageButton()
    }

    private fun selectedModel(): String? = models.getOrNull(binding.modelSpinner.selectedItemPosition)

    /** Show the image button only when the selected model accepts images. */
    private fun updateImageButton() {
        val m = selectedModel()
        binding.imageButton.visibility =
            if (m != null && visionIds.contains(m)) View.VISIBLE else View.GONE
    }

    // --- attachments -------------------------------------------------------

    private fun extractFiles(uris: List<Uri>) {
        lifecycleScope.launch {
            for (uri in uris) {
                val name = queryName(uri)
                val res = withContext(Dispatchers.IO) {
                    try {
                        val bytes = contentResolver.openInputStream(uri)?.use { it.readBytes() }
                            ?: return@withContext null
                        client.extractDocument(bytes, name)
                    } catch (e: Exception) { null }
                }
                if (res == null) { toast("Couldn't read $name"); continue }
                if (res.has("error")) { toast("Couldn't read $name: ${res.optString("error")}"); continue }
                val text = res.optString("text")
                if (text.isBlank()) { toast("No readable text in $name"); continue }
                attachments.add(name to text)
            }
            renderAttachments()
        }
    }

    private fun queryName(uri: Uri): String {
        var name = "document"
        try {
            contentResolver.query(uri, null, null, null, null)?.use { c ->
                val idx = c.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                if (idx >= 0 && c.moveToFirst()) name = c.getString(idx) ?: name
            }
        } catch (_: Exception) { }
        return name
    }

    private fun encodeImages(uris: List<Uri>) {
        lifecycleScope.launch {
            for (uri in uris) {
                val name = queryName(uri)
                val dataUrl = withContext(Dispatchers.IO) {
                    try {
                        val bytes = contentResolver.openInputStream(uri)?.use { it.readBytes() }
                            ?: return@withContext null
                        val mime = contentResolver.getType(uri) ?: "image/jpeg"
                        val b64 = android.util.Base64.encodeToString(bytes, android.util.Base64.NO_WRAP)
                        "data:$mime;base64,$b64"
                    } catch (e: Exception) { null }
                }
                if (dataUrl == null) { toast("Couldn't read $name"); continue }
                stagedImages.add(name to dataUrl)
            }
            renderAttachments()
        }
    }

    private fun renderAttachments() {
        val chips = attachments.map { "📎 ${it.first}" } + stagedImages.map { "🖼 ${it.first}" }
        if (chips.isEmpty()) {
            binding.attachmentRow.visibility = View.GONE
        } else {
            binding.attachmentRow.visibility = View.VISIBLE
            binding.attachmentText.text = chips.joinToString("  ")
        }
    }

    private fun toast(msg: String) = runOnUiThread {
        android.widget.Toast.makeText(this, msg, android.widget.Toast.LENGTH_SHORT).show()
    }

    // --- send / stream -----------------------------------------------------

    private fun send() {
        val typed = binding.input.text.toString().trim()
        if (typed.isEmpty() && attachments.isEmpty() && stagedImages.isEmpty()) return
        val model = selectedModel()
        if (model == null) { toast("No model selected."); return }
        if (currentId == null) newChat()

        val content = buildContent(typed, attachments, stagedImages.map { it.first })
        val imageUrls = stagedImages.map { it.second }
        items.add(ChatItem("user", content))
        val assistant = ChatItem("assistant", "")
        items.add(assistant)
        val assistantIndex = items.lastIndex
        adapter.notifyItemRangeInserted(assistantIndex - 1, 2)
        scrollToEnd()
        binding.input.setText("")
        attachments.clear(); stagedImages.clear(); renderAttachments()
        setStreaming(true)
        val gen = ++streamGen // this stream's generation; guards late callbacks

        val history = items.dropLast(1).map { it.role to it.content }
        saveCurrent() // persist the user turn immediately

        streamCall = client.streamChat(
            model = model,
            messages = history,
            imageUrls = imageUrls,
            onToken = { token ->
                runOnUiThread {
                    if (gen != streamGen) return@runOnUiThread // superseded (switched chat)
                    assistant.content += token
                    adapter.notifyItemChanged(assistantIndex)
                    scrollToEnd()
                }
            },
            onDone = {
                runOnUiThread {
                    if (gen != streamGen) return@runOnUiThread
                    if (assistant.content.isEmpty()) assistant.content = "(no response)"
                    adapter.notifyItemChanged(assistantIndex)
                    setStreaming(false)
                    saveCurrent(); loadSessions()
                }
            },
            onError = { err ->
                runOnUiThread {
                    if (gen != streamGen) return@runOnUiThread
                    assistant.content = if (assistant.content.isEmpty()) "⚠ $err" else assistant.content + "\n\n⚠ $err"
                    adapter.notifyItemChanged(assistantIndex)
                    setStreaming(false)
                    saveCurrent()
                }
            }
        )
    }

    private fun buildContent(
        text: String,
        files: List<Pair<String, String>>,
        imageNames: List<String>,
    ): String {
        if (files.isEmpty() && imageNames.isEmpty()) return text
        val parts = files.map { "[file: ${it.first}]\n${it.second}" } + imageNames.map { "[image: $it]" }
        return "$text${ChatAdapter.ATTACH_DELIM}${parts.joinToString("\n\n")}"
    }

    private fun stopStreaming() {
        cancelActiveStream()
        setStreaming(false)
        saveCurrent() // keep whatever was streamed so far
    }

    private fun setStreaming(on: Boolean) {
        if (!on) streamCall = null
        binding.sendButton.text = if (on) "Stop" else "Send"
        binding.input.isEnabled = !on
    }

    private fun scrollToEnd() {
        if (items.isNotEmpty()) binding.messagesList.scrollToPosition(items.size - 1)
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
            val stage = loading.optString("stage", "").ifBlank { phaseLabel(loading.optString("phase", "loading")) }
            val model = loading.optString("model", "")
            val remote = loading.optInt("remote_count", 0)
            val elapsed = loading.optDouble("elapsed_s", 0.0)
            val idle = loading.optDouble("idle_s", 0.0)
            val pct = if (loading.isNull("percent")) null else loading.optDouble("percent")
            val bytesTotal = if (loading.isNull("bytes_total")) 0L else loading.optLong("bytes_total")

            binding.poolTitle.text = "Loading $model across $nodeCount device(s) — $stage"
            binding.poolProgress.isIndeterminate = pct == null
            if (pct != null) binding.poolProgress.progress = pct.toInt()

            // percent is a coarse stage estimate; no reliable ETA / transferred bytes.
            val parts = mutableListOf<String>()
            parts.add(if (pct != null) "~${pct.toInt()}% (stage)" else "working…")
            parts.add("elapsed ${fmtDur(elapsed)}")
            if (bytesTotal > 0) parts.add("~${fmtBytes(bytesTotal)} to $remote worker(s)")
            binding.poolStats.text = parts.joinToString("  ·  ")
            binding.poolLog.text = if (idle > 20)
                "⏳ still working — no update in ${fmtDur(idle)} (slow worker over WiFi)"
            else loading.optString("last_log", "")
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
