package com.localy.worker

import android.content.Context
import android.net.nsd.NsdManager
import android.net.nsd.NsdServiceInfo
import android.os.Build
import android.util.Log

/**
 * Advertises this phone as a Localy pool worker over mDNS, matching the
 * `_localy._tcp` service + TXT keys (label, budget, node_id) that the desktop
 * coordinator's discovery browser expects. This is what makes it "just connect":
 * the coordinator finds the phone automatically on the same WiFi/hotspot.
 */
class NsdAdvertiser(private val context: Context) {

    companion object {
        private const val TAG = "LocalyNsd"
        private const val SERVICE_TYPE = "_localy._tcp."
    }

    private var nsdManager: NsdManager? = null
    private var listener: NsdManager.RegistrationListener? = null

    fun register(port: Int, label: String, budgetBytes: Long) {
        val info = NsdServiceInfo().apply {
            serviceName = "${Build.MODEL}-$port".replace(" ", "-")
            serviceType = SERVICE_TYPE
            setPort(port)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
                setAttribute("label", label)
                setAttribute("budget", budgetBytes.toString())
                setAttribute("node_id", "$label:$port")
            }
        }

        val mgr = context.getSystemService(Context.NSD_SERVICE) as NsdManager
        val l = object : NsdManager.RegistrationListener {
            override fun onServiceRegistered(info: NsdServiceInfo) {
                Log.i(TAG, "advertised as ${info.serviceName}")
            }
            override fun onRegistrationFailed(info: NsdServiceInfo, errorCode: Int) {
                Log.e(TAG, "mDNS registration failed: $errorCode")
            }
            override fun onServiceUnregistered(info: NsdServiceInfo) {
                Log.i(TAG, "mDNS unregistered")
            }
            override fun onUnregistrationFailed(info: NsdServiceInfo, errorCode: Int) {
                Log.e(TAG, "mDNS unregistration failed: $errorCode")
            }
        }
        mgr.registerService(info, NsdManager.PROTOCOL_DNS_SD, l)
        nsdManager = mgr
        listener = l
    }

    fun unregister() {
        try {
            listener?.let { nsdManager?.unregisterService(it) }
        } catch (e: Exception) {
            Log.w(TAG, "unregister failed: ${e.message}")
        }
        listener = null
        nsdManager = null
    }
}
