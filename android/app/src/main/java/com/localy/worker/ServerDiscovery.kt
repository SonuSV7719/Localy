package com.localy.worker

import android.content.Context
import android.net.nsd.NsdManager
import android.net.nsd.NsdServiceInfo
import android.util.Log
import java.util.ArrayDeque

/**
 * Discovers Localy API servers on the LAN via mDNS (`_localy-api._tcp`, which
 * the desktop advertises). Reports each as a `http://host:port` base URL so the
 * chat screen can auto-fill the address — the user only pastes a key.
 *
 * Resolves are serialized: pre-Android-12 NsdManager allows only ONE in-flight
 * resolveService; overlapping calls fail with FAILURE_ALREADY_ACTIVE and the
 * device silently never appears. We queue and resolve one at a time.
 */
class ServerDiscovery(context: Context) {

    data class Server(val name: String, val host: String, val port: Int) {
        val baseUrl: String get() = "http://$host:$port"
    }

    private val nsd = context.getSystemService(Context.NSD_SERVICE) as NsdManager
    private var discoveryListener: NsdManager.DiscoveryListener? = null
    private val found = LinkedHashMap<String, Server>()

    private val pending = ArrayDeque<NsdServiceInfo>()
    private var resolving = false
    private var onChange: ((List<Server>) -> Unit)? = null

    fun start(onChange: (List<Server>) -> Unit) {
        stop()
        this.onChange = onChange
        val listener = object : NsdManager.DiscoveryListener {
            override fun onDiscoveryStarted(serviceType: String) {}
            override fun onStartDiscoveryFailed(serviceType: String, errorCode: Int) {
                Log.e(TAG, "discovery start failed: $errorCode")
            }
            override fun onStopDiscoveryFailed(serviceType: String, errorCode: Int) {}
            override fun onDiscoveryStopped(serviceType: String) {}

            override fun onServiceFound(info: NsdServiceInfo) {
                synchronized(pending) { pending.add(info) }
                resolveNext()
            }

            override fun onServiceLost(info: NsdServiceInfo) {
                found.remove(info.serviceName)
                this@ServerDiscovery.onChange?.invoke(found.values.toList())
            }
        }
        discoveryListener = listener
        try {
            nsd.discoverServices(SERVICE_TYPE, NsdManager.PROTOCOL_DNS_SD, listener)
        } catch (e: Exception) {
            Log.e(TAG, "discoverServices failed: ${e.message}")
        }
    }

    @Synchronized
    private fun resolveNext() {
        if (resolving) return
        val info = synchronized(pending) { if (pending.isEmpty()) null else pending.removeFirst() } ?: return
        resolving = true
        val resolveListener = object : NsdManager.ResolveListener {
            override fun onResolveFailed(info: NsdServiceInfo, errorCode: Int) {
                Log.w(TAG, "resolve failed: $errorCode")
                resolving = false
                resolveNext()
            }
            override fun onServiceResolved(resolved: NsdServiceInfo) {
                @Suppress("DEPRECATION")
                val host = resolved.host?.hostAddress
                if (host != null) {
                    found[resolved.serviceName] = Server(resolved.serviceName, host, resolved.port)
                    onChange?.invoke(found.values.toList())
                }
                resolving = false
                resolveNext()
            }
        }
        try {
            nsd.resolveService(info, resolveListener)
        } catch (e: Exception) {
            Log.w(TAG, "resolveService failed: ${e.message}")
            resolving = false
            resolveNext()
        }
    }

    fun stop() {
        discoveryListener?.let {
            try {
                nsd.stopServiceDiscovery(it)
            } catch (e: Exception) {
                Log.w(TAG, "stopServiceDiscovery failed: ${e.message}")
            }
        }
        discoveryListener = null
        onChange = null
        resolving = false
        synchronized(pending) { pending.clear() }
        found.clear()
    }

    companion object {
        private const val TAG = "LocalyServerDiscovery"
        // Must match backend MDNS_API_SERVICE_TYPE ("_localy-api._tcp.local.").
        private const val SERVICE_TYPE = "_localy-api._tcp."
    }
}
