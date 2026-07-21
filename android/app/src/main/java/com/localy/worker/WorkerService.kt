package com.localy.worker

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.net.wifi.WifiManager
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import androidx.core.app.NotificationCompat

/**
 * Foreground service that keeps the rpc-server alive and advertised while the
 * phone contributes to the pool. Foreground + wakelock so Android doesn't kill
 * it or sleep the CPU mid-inference.
 */
class WorkerService : Service() {

    companion object {
        const val ACTION_START = "com.localy.worker.START"
        const val ACTION_STOP = "com.localy.worker.STOP"
        private const val CHANNEL_ID = "localy_worker"
        private const val NOTIF_ID = 1

        @Volatile var running = false
            private set
        @Volatile var statusText = "Idle"
            private set
    }

    private lateinit var rpc: RpcWorker
    private lateinit var advertiser: NsdAdvertiser
    private var wakeLock: PowerManager.WakeLock? = null
    // Keep the WiFi radio in high-perf mode (don't power-manage the RPC socket)
    // and keep multicast reception alive (so mDNS/NSD keeps answering) even when
    // the screen is off / Doze kicks in. Without these the desktop coordinator
    // loses the worker a minute or two after the screen sleeps.
    private var wifiLock: WifiManager.WifiLock? = null
    private var multicastLock: WifiManager.MulticastLock? = null

    override fun onCreate() {
        super.onCreate()
        rpc = RpcWorker(this)
        advertiser = NsdAdvertiser(this)
        createChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_STOP -> {
                stopWorker()
                return START_NOT_STICKY
            }
            else -> startWorker()
        }
        return START_STICKY
    }

    private fun startWorker() {
        if (running) return
        val cap = HardwareInfo.capacity(this)
        val offeredGb = cap.offeredBytes / (1024.0 * 1024 * 1024)

        startForeground(NOTIF_ID, buildNotification("Starting…"))

        val ok = rpc.start(port = RpcWorker.DEFAULT_PORT, threads = cap.threads)
        if (!ok) {
            statusText = "Failed: ${rpc.lastError}"
            updateNotification(statusText)
            return
        }

        advertiser.register(
            port = RpcWorker.DEFAULT_PORT,
            label = Build.MODEL ?: "Android",
            budgetBytes = cap.offeredBytes,
            // Phones are slow nodes — advertise a modest compute score so the
            // coordinator assigns them fewer layers (less pipeline bottleneck).
            computeScore = cap.threads.toDouble()
        )

        acquireWakeLock()
        acquireWifiLocks()
        running = true
        statusText = "Contributing ~%.1f GB · discoverable on WiFi".format(offeredGb)
        updateNotification(statusText)
    }

    private fun stopWorker() {
        advertiser.unregister()
        rpc.stop()
        releaseWakeLock()
        releaseWifiLocks()
        running = false
        statusText = "Stopped"
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    override fun onDestroy() {
        stopWorker()
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    private fun acquireWakeLock() {
        val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
        wakeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "Localy:worker").apply {
            setReferenceCounted(false)
            acquire(6 * 60 * 60 * 1000L) // safety cap: 6h
        }
    }

    private fun releaseWakeLock() {
        wakeLock?.let { if (it.isHeld) it.release() }
        wakeLock = null
    }

    @Suppress("DEPRECATION")
    private fun acquireWifiLocks() {
        val wifi = applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager
        // High-perf lock keeps the WiFi radio from dozing the RPC TCP socket.
        val mode = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q)
            WifiManager.WIFI_MODE_FULL_LOW_LATENCY
        else
            WifiManager.WIFI_MODE_FULL_HIGH_PERF
        wifiLock = wifi.createWifiLock(mode, "Localy:wifi").apply {
            setReferenceCounted(false)
            acquire()
        }
        // Multicast lock keeps mDNS/NSD announcements flowing so the desktop
        // coordinator keeps seeing this worker while the screen is off.
        multicastLock = wifi.createMulticastLock("Localy:mdns").apply {
            setReferenceCounted(false)
            acquire()
        }
    }

    private fun releaseWifiLocks() {
        wifiLock?.let { if (it.isHeld) it.release() }
        wifiLock = null
        multicastLock?.let { if (it.isHeld) it.release() }
        multicastLock = null
    }

    private fun createChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val ch = NotificationChannel(
                CHANNEL_ID, "Localy Pool Worker", NotificationManager.IMPORTANCE_LOW
            )
            (getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager)
                .createNotificationChannel(ch)
        }
    }

    private fun buildNotification(text: String): Notification =
        NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("Localy — sharing this device")
            .setContentText(text)
            .setSmallIcon(android.R.drawable.stat_sys_upload)
            .setOngoing(true)
            .build()

    private fun updateNotification(text: String) {
        (getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager)
            .notify(NOTIF_ID, buildNotification(text))
    }
}
