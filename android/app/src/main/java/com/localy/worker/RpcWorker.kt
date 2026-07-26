package com.localy.worker

import android.content.Context
import android.util.Log
import java.io.File
import java.util.concurrent.TimeUnit

/**
 * Runs the bundled ggml-rpc-server (packaged as libggml-rpc-server.so) as a
 * child process. Execution is permitted from the app's nativeLibraryDir, so we
 * exec the extracted .so directly — no root, no Termux, no setup.
 */
class RpcWorker(private val context: Context) {

    companion object {
        private const val TAG = "LocalyRpcWorker"
        private const val LIB_NAME = "libggml-rpc-server.so"
        const val DEFAULT_PORT = 50052
    }

    private var process: Process? = null
    @Volatile var lastError: String? = null
        private set

    val isRunning: Boolean
        get() = process?.isAlive == true

    private fun binaryPath(): File {
        val nativeDir = context.applicationInfo.nativeLibraryDir
        return File(nativeDir, LIB_NAME)
    }

    /** Start the rpc-server. Returns true if it launched and stayed alive. */
    fun start(port: Int = DEFAULT_PORT, threads: Int = 2): Boolean {
        if (isRunning) return true
        val bin = binaryPath()
        if (!bin.exists()) {
            lastError = "worker binary missing at ${bin.absolutePath}"
            Log.e(TAG, lastError!!)
            return false
        }
        return try {
            val cacheRoot = CacheManager.cacheRoot(context)
            val pb = ProcessBuilder(
                bin.absolutePath,
                "--host", "0.0.0.0",
                "--port", port.toString(),
                "--threads", threads.toString(),
                "--cache"
            )
            pb.environment()["LLAMA_CACHE"] = cacheRoot.absolutePath
            pb.redirectErrorStream(true)
            pb.directory(context.filesDir)
            val proc = pb.start()
            process = proc

            // Drain output to logcat so we can diagnose issues.
            Thread {
                try {
                    proc.inputStream.bufferedReader().useLines { lines ->
                        lines.forEach { Log.i(TAG, "[rpc] $it") }
                    }
                } catch (_: Exception) {
                    // Expected when stop() closes the process stream during
                    // shutdown or failed startup.
                }
            }.apply { isDaemon = true }.start()

            // Give it a moment; if it died immediately, report failure.
            Thread.sleep(1500)
            if (!proc.isAlive) {
                lastError = "rpc-server exited immediately (code ${proc.exitValue()})"
                Log.e(TAG, lastError!!)
                false
            } else {
                Log.i(TAG, "rpc-server running on :$port with $threads threads; cache=${cacheRoot.absolutePath}")
                true
            }
        } catch (e: Exception) {
            lastError = "failed to launch rpc-server: ${e.message}"
            Log.e(TAG, lastError!!, e)
            false
        }
    }

    fun stop() {
        process?.let { p ->
            try {
                p.destroy()
                if (!p.waitFor(1500, TimeUnit.MILLISECONDS) && p.isAlive) {
                    p.destroyForcibly()
                    p.waitFor(1500, TimeUnit.MILLISECONDS)
                }
            } catch (_: Exception) {
            }
        }
        process = null
        Log.i(TAG, "rpc-server stopped")
    }

}
