package com.localy.worker

import android.content.Context
import android.net.nsd.NsdManager
import android.net.nsd.NsdServiceInfo
import android.os.Build
import android.util.Log

/**
 * Discovers Localy API servers on the LAN via mDNS (`_localy-api._tcp`, which
 * the desktop advertises). Reports each as a `http://host:port` base URL so the
 * chat screen can auto-fill the address — the user only needs to paste a key.
 */
class ServerDiscovery(context: Context) {

    data class Server(val name: String, val host: String, val port: Int) {
        val baseUrl: String get() = "http://$host:$port"
    }

    private val nsd = context.getSystemService(Context.NSD_SERVICE) as NsdManager
    private var discoveryListener: NsdManager.DiscoveryListener? = null
    private val found = LinkedHashMap<String, Server>()

    fun start(onChange: (List<Server>) -> Unit) {
        stop()
        val listener = object : NsdManager.DiscoveryListener {
            override fun onDiscoveryStarted(serviceType: String) {}
            override fun onStartDiscoveryFailed(serviceType: String, errorCode: Int) {
                Log.e(TAG, "discovery start failed: $errorCode")
            }
            override fun onStopDiscoveryFailed(serviceType: String, errorCode: Int) {}
            override fun onDiscoveryStopped(serviceType: String) {}

            override fun onServiceFound(info: NsdServiceInfo) {
                resolve(info, onChange)
            }

            override fun onServiceLost(info: NsdServiceInfo) {
                found.remove(info.serviceName)
                onChange(found.values.toList())
            }
        }
        discoveryListener = listener
        try {
            nsd.discoverServices(SERVICE_TYPE, NsdManager.PROTOCOL_DNS_SD, listener)
        } catch (e: Exception) {
            Log.e(TAG, "discoverServices failed: ${e.message}")
        }
    }

    private fun resolve(info: NsdServiceInfo, onChange: (List<Server>) -> Unit) {
        val resolveListener = object : NsdManager.ResolveListener {
            override fun onResolveFailed(info: NsdServiceInfo, errorCode: Int) {
                Log.w(TAG, "resolve failed: $errorCode")
            }
            override fun onServiceResolved(resolved: NsdServiceInfo) {
                @Suppress("DEPRECATION")
                val host = resolved.host?.hostAddress ?: return
                val server = Server(resolved.serviceName, host, resolved.port)
                found[resolved.serviceName] = server
                onChange(found.values.toList())
            }
        }
        try {
            nsd.resolveService(info, resolveListener)
        } catch (e: Exception) {
            Log.w(TAG, "resolveService failed: ${e.message}")
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
        found.clear()
    }

    companion object {
        private const val TAG = "LocalyServerDiscovery"
        // Must match backend MDNS_API_SERVICE_TYPE ("_localy-api._tcp.local.").
        // Android's NsdManager expects the type without the trailing ".local."
        private const val SERVICE_TYPE = "_localy-api._tcp."
    }
}
