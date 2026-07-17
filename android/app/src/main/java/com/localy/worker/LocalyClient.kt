package com.localy.worker

import okhttp3.Call
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/**
 * Minimal client for a Localy server's OpenAI-compatible API over the LAN.
 * All requests carry the API key (LAN access is key-gated on the server).
 */
class LocalyClient(
    @Volatile var baseUrl: String,
    @Volatile var apiKey: String,
) {

    private val client = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(0, TimeUnit.SECONDS)   // streaming responses stay open
        .writeTimeout(30, TimeUnit.SECONDS)
        .build()

    private fun newRequest(path: String): Request.Builder {
        val b = Request.Builder().url(baseUrl.trimEnd('/') + path)
        if (apiKey.isNotBlank()) b.header("Authorization", "Bearer $apiKey")
        return b
    }

    private val json = "application/json; charset=utf-8".toMediaType()

    /** True if /health responds ok (loopback-style quick check, still keyed). */
    fun ping(): Boolean = try {
        client.newCall(newRequest("/health").get().build()).execute().use { it.isSuccessful }
    } catch (e: Exception) {
        false
    }

    /** List available model ids from /v1/models. Throws on HTTP/parse error. */
    fun listModels(): List<String> {
        client.newCall(newRequest("/v1/models").get().build()).execute().use { resp ->
            val body = resp.body?.string().orEmpty()
            if (!resp.isSuccessful) throw RuntimeException(errorMessage(resp.code, body))
            val data = JSONObject(body).optJSONArray("data") ?: JSONArray()
            return (0 until data.length()).mapNotNull { data.getJSONObject(it).optString("id").ifBlank { null } }
        }
    }

    /** Upload a document; the server returns extracted text to use as context. */
    fun extractDocument(bytes: ByteArray, filename: String): JSONObject {
        val body = MultipartBody.Builder()
            .setType(MultipartBody.FORM)
            .addFormDataPart(
                "file", filename,
                bytes.toRequestBody("application/octet-stream".toMediaType())
            )
            .build()
        client.newCall(newRequest("/system/extract").post(body).build()).execute().use { resp ->
            val s = resp.body?.string().orEmpty()
            if (!resp.isSuccessful) throw RuntimeException(errorMessage(resp.code, s))
            return JSONObject(s)
        }
    }

    /** Ids of models that accept images (supports_vision), from /system/models. */
    fun visionModelIds(): Set<String> = try {
        client.newCall(newRequest("/system/models").get().build()).execute().use { resp ->
            if (!resp.isSuccessful) emptySet()
            else {
                val arr = JSONArray(resp.body?.string().orEmpty())
                val out = mutableSetOf<String>()
                for (i in 0 until arr.length()) {
                    val m = arr.getJSONObject(i)
                    if (m.optBoolean("supports_vision")) out.add(m.optString("id"))
                }
                out
            }
        }
    } catch (e: Exception) {
        emptySet()
    }

    /** Current pool status (including the `loading` progress block), or null. */
    fun poolStatus(): JSONObject? = try {
        client.newCall(newRequest("/pool/status").get().build()).execute().use { resp ->
            val body = resp.body?.string().orEmpty()
            if (resp.isSuccessful) JSONObject(body) else null
        }
    } catch (e: Exception) {
        null
    }

    /**
     * Stream a chat completion (SSE). Callbacks fire on a background thread —
     * marshal to the UI thread in the caller. Returns the Call so it can be
     * cancelled (Stop button).
     */
    fun streamChat(
        model: String,
        messages: List<Pair<String, String>>,
        imageUrls: List<String> = emptyList(),
        onToken: (String) -> Unit,
        onDone: () -> Unit,
        onError: (String) -> Unit,
    ): Call {
        val payload = JSONObject().apply {
            put("model", model)
            put("stream", true)
            put("temperature", 0.7)
            put("messages", JSONArray().apply {
                messages.forEachIndexed { i, (role, content) ->
                    val obj = JSONObject().put("role", role)
                    if (i == messages.lastIndex && imageUrls.isNotEmpty()) {
                        // Send the current turn as OpenAI multimodal parts.
                        val parts = JSONArray()
                        parts.put(JSONObject().put("type", "text").put("text", content))
                        imageUrls.forEach { url ->
                            parts.put(
                                JSONObject().put("type", "image_url")
                                    .put("image_url", JSONObject().put("url", url))
                            )
                        }
                        obj.put("content", parts)
                    } else {
                        obj.put("content", content)
                    }
                    put(obj)
                }
            })
        }
        val call = client.newCall(
            newRequest("/v1/chat/completions")
                .post(payload.toString().toRequestBody(json))
                .build()
        )
        Thread {
            try {
                call.execute().use { resp ->
                    if (!resp.isSuccessful) {
                        onError(errorMessage(resp.code, resp.body?.string().orEmpty()))
                        return@Thread
                    }
                    val source = resp.body?.source() ?: run { onError("Empty response"); return@Thread }
                    while (!source.exhausted()) {
                        val line = source.readUtf8Line() ?: break
                        val trimmed = line.trim()
                        if (!trimmed.startsWith("data:")) continue
                        val payloadStr = trimmed.removePrefix("data:").trim()
                        if (payloadStr == "[DONE]") { onDone(); return@Thread }
                        try {
                            val delta = JSONObject(payloadStr)
                                .optJSONArray("choices")?.optJSONObject(0)
                                ?.optJSONObject("delta")?.optString("content").orEmpty()
                            if (delta.isNotEmpty()) onToken(delta)
                        } catch (_: Exception) { /* ignore malformed keepalive lines */ }
                    }
                    onDone()
                }
            } catch (e: Exception) {
                if (call.isCanceled()) onDone() else onError(e.message ?: "Network error")
            }
        }.start()
        return call
    }

    private fun errorMessage(code: Int, body: String): String {
        val hint = when (code) {
            401, 403 -> "Access denied — check the API key (generate one on the PC's API Access tab)."
            404 -> "Not found — is this a Localy server?"
            else -> "Server returned HTTP $code."
        }
        val detail = try {
            JSONObject(body).optString("message").ifBlank { null }
        } catch (e: Exception) { null }
        return if (detail != null) "$hint ($detail)" else hint
    }
}
