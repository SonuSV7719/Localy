package com.localy.worker

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper

/** A stored chat session (metadata; messages live in the messages table). */
data class Conversation(
    val id: String,
    var title: String,
    var modelId: String,
    var updatedAt: Long,
    var archived: Boolean,
)

/**
 * On-device SQLite store for chat sessions and their messages. Everything stays
 * local to the phone — nothing is uploaded. Uses the built-in SQLiteOpenHelper
 * (no extra dependencies / annotation processors).
 */
class ChatDb(context: Context) : SQLiteOpenHelper(context, DB_NAME, null, DB_VERSION) {

    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL(
            """CREATE TABLE conversations (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                model_id TEXT NOT NULL DEFAULT '',
                updated_at INTEGER NOT NULL,
                archived INTEGER NOT NULL DEFAULT 0
            )"""
        )
        db.execSQL(
            """CREATE TABLE messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                seq INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL
            )"""
        )
        db.execSQL("CREATE INDEX idx_messages_conv ON messages(conversation_id, seq)")
    }

    override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) {
        // v1 only so far; nothing to migrate.
    }

    // --- conversations -----------------------------------------------------

    fun conversations(archived: Boolean): List<Conversation> {
        val out = mutableListOf<Conversation>()
        readableDatabase.rawQuery(
            "SELECT id,title,model_id,updated_at,archived FROM conversations WHERE archived=? ORDER BY updated_at DESC",
            arrayOf(if (archived) "1" else "0"),
        ).use { c ->
            while (c.moveToNext()) {
                out.add(
                    Conversation(
                        id = c.getString(0),
                        title = c.getString(1),
                        modelId = c.getString(2),
                        updatedAt = c.getLong(3),
                        archived = c.getInt(4) == 1,
                    )
                )
            }
        }
        return out
    }

    fun createConversation(id: String, title: String, modelId: String, now: Long) {
        val cv = ContentValues().apply {
            put("id", id)
            put("title", title)
            put("model_id", modelId)
            put("updated_at", now)
            put("archived", 0)
        }
        writableDatabase.insert("conversations", null, cv)
    }

    fun updateMeta(id: String, title: String, modelId: String, now: Long) {
        val cv = ContentValues().apply {
            put("title", title)
            put("model_id", modelId)
            put("updated_at", now)
        }
        writableDatabase.update("conversations", cv, "id=?", arrayOf(id))
    }

    fun rename(id: String, title: String) {
        val cv = ContentValues().apply { put("title", title) }
        writableDatabase.update("conversations", cv, "id=?", arrayOf(id))
    }

    fun setArchived(id: String, archived: Boolean) {
        val cv = ContentValues().apply { put("archived", if (archived) 1 else 0) }
        writableDatabase.update("conversations", cv, "id=?", arrayOf(id))
    }

    fun deleteConversation(id: String) {
        writableDatabase.delete("messages", "conversation_id=?", arrayOf(id))
        writableDatabase.delete("conversations", "id=?", arrayOf(id))
    }

    // --- messages ----------------------------------------------------------

    fun messages(convId: String): MutableList<ChatItem> {
        val out = mutableListOf<ChatItem>()
        readableDatabase.rawQuery(
            "SELECT role,content FROM messages WHERE conversation_id=? ORDER BY seq ASC",
            arrayOf(convId),
        ).use { c ->
            while (c.moveToNext()) out.add(ChatItem(c.getString(0), c.getString(1)))
        }
        return out
    }

    /** Replace all messages for a conversation (called after a turn completes). */
    fun saveMessages(convId: String, items: List<ChatItem>) {
        val db = writableDatabase
        db.beginTransaction()
        try {
            db.delete("messages", "conversation_id=?", arrayOf(convId))
            items.forEachIndexed { i, m ->
                val cv = ContentValues().apply {
                    put("conversation_id", convId)
                    put("seq", i)
                    put("role", m.role)
                    put("content", m.content)
                }
                db.insert("messages", null, cv)
            }
            db.setTransactionSuccessful()
        } finally {
            db.endTransaction()
        }
    }

    companion object {
        private const val DB_NAME = "localy_chats.db"
        private const val DB_VERSION = 1
    }
}
