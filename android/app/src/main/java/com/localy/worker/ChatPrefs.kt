package com.localy.worker

import android.content.Context

/** Persists the Localy server the phone chats with (host:port + API key). */
class ChatPrefs(context: Context) {

    private val prefs = context.getSharedPreferences("localy_chat", Context.MODE_PRIVATE)

    var baseUrl: String
        get() = prefs.getString(KEY_URL, "") ?: ""
        set(value) = prefs.edit().putString(KEY_URL, value).apply()

    var apiKey: String
        get() = prefs.getString(KEY_KEY, "") ?: ""
        set(value) = prefs.edit().putString(KEY_KEY, value).apply()

    var lastModel: String
        get() = prefs.getString(KEY_MODEL, "") ?: ""
        set(value) = prefs.edit().putString(KEY_MODEL, value).apply()

    val isConfigured: Boolean
        get() = baseUrl.isNotBlank() && apiKey.isNotBlank()

    companion object {
        private const val KEY_URL = "base_url"
        private const val KEY_KEY = "api_key"
        private const val KEY_MODEL = "last_model"
    }
}
