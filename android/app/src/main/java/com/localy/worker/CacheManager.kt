package com.localy.worker

import android.content.Context
import java.io.File

/**
 * Manages the on-device RPC weight cache (populated by ggml-rpc-server's
 * --cache, pointed at filesDir/rpc-cache via LLAMA_CACHE). These are cached
 * tensor blocks streamed from coordinators so models aren't re-transferred.
 *
 * Enumeration and deletion are done off the main thread by the caller.
 */
object CacheManager {

    private const val CACHE_SUBDIR = "rpc-cache"

    data class Entry(
        val path: String,
        val name: String,
        val sizeBytes: Long,
        val lastModified: Long,
    )

    fun cacheDir(context: Context): File =
        File(context.filesDir, CACHE_SUBDIR).apply { mkdirs() }

    /** Top-level cache entries (files or subdirs), each with its recursive size. */
    fun list(context: Context): List<Entry> {
        val dir = cacheDir(context)
        val children = dir.listFiles() ?: return emptyList()
        return children.map { f ->
            Entry(
                path = f.absolutePath,
                name = f.name,
                sizeBytes = sizeOf(f),
                lastModified = f.lastModified(),
            )
        }.sortedByDescending { it.sizeBytes }
    }

    fun totalSize(context: Context): Long = sizeOf(cacheDir(context))

    /** Delete the given entries. Returns the number successfully removed. */
    fun delete(paths: Collection<String>): Int {
        var removed = 0
        for (p in paths) {
            if (deleteRecursively(File(p))) removed++
        }
        return removed
    }

    /** Wipe the entire cache. */
    fun clearAll(context: Context): Boolean {
        val dir = cacheDir(context)
        val ok = dir.listFiles()?.all { deleteRecursively(it) } ?: true
        return ok
    }

    private fun sizeOf(f: File): Long =
        if (f.isDirectory) (f.listFiles()?.sumOf { sizeOf(it) } ?: 0L) else f.length()

    private fun deleteRecursively(f: File): Boolean {
        if (f.isDirectory) f.listFiles()?.forEach { deleteRecursively(it) }
        return f.delete()
    }

    fun humanSize(bytes: Long): String {
        if (bytes < 1024) return "$bytes B"
        val kb = bytes / 1024.0
        if (kb < 1024) return "%.0f KB".format(kb)
        val mb = kb / 1024.0
        if (mb < 1024) return "%.1f MB".format(mb)
        return "%.2f GB".format(mb / 1024.0)
    }
}
