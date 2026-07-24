package com.localy.worker

import android.content.Context
import android.net.TrafficStats
import android.util.Log
import java.net.ServerSocket
import java.net.SocketException
import kotlin.concurrent.thread

/** Read-only LAN endpoint exposing the worker app's received network bytes. */
class WorkerMetricsServer(private val context: Context) {

    companion object {
        const val DEFAULT_PORT = 50053
        private const val TAG = "LocalyMetrics"
    }

    @Volatile private var running = false
    private var socket: ServerSocket? = null

    fun start(port: Int = DEFAULT_PORT): Boolean {
        if (running) return true
        return try {
            socket = ServerSocket(port)
            running = true
            thread(name = "localy-metrics", isDaemon = true) {
                while (running) {
                    try {
                        socket?.accept()?.use(::respond)
                    } catch (_: SocketException) {
                        // Closing the socket during service shutdown wakes accept().
                    } catch (e: Exception) {
                        if (running) Log.w(TAG, "metrics request failed", e)
                    }
                }
            }
            true
        } catch (e: Exception) {
            Log.w(TAG, "metrics server failed to start", e)
            socket = null
            false
        }
    }

    private fun respond(client: java.net.Socket) {
        val input = client.getInputStream().bufferedReader()
        val request = input.readLine().orEmpty()
        while (input.readLine()?.isNotEmpty() == true) { }
        val body = if (request.startsWith("GET /metrics ")) {
            val bytes = TrafficStats.getUidRxBytes(context.applicationInfo.uid)
            "{\"rx_bytes\":${if (bytes >= 0) bytes else 0},\"running\":true}"
        } else {
            "{\"error\":\"not found\"}"
        }
        val status = if (request.startsWith("GET /metrics ")) "200 OK" else "404 Not Found"
        client.getOutputStream().bufferedWriter().use { out ->
            out.write("HTTP/1.1 $status\r\nContent-Type: application/json\r\nContent-Length: ${body.toByteArray().size}\r\nConnection: close\r\n\r\n$body")
            out.flush()
        }
    }

    fun stop() {
        running = false
        try { socket?.close() } catch (_: Exception) { }
        socket = null
    }
}
