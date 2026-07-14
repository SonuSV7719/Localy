package com.localy.worker

import android.app.ActivityManager
import android.content.Context

/** Derives how much this phone should offer to the pool. */
object HardwareInfo {

    data class Capacity(val offeredBytes: Long, val totalBytes: Long, val threads: Int)

    // Offer a conservative fraction of total RAM (phones need headroom for the OS).
    private const val OFFER_FRACTION = 0.45

    fun capacity(context: Context): Capacity {
        val am = context.getSystemService(Context.ACTIVITY_SERVICE) as ActivityManager
        val mi = ActivityManager.MemoryInfo()
        am.getMemoryInfo(mi)
        val total = mi.totalMem
        val offered = (total * OFFER_FRACTION).toLong()
        // Use up to 4 threads; leave cores for the OS so the phone stays responsive.
        val threads = Runtime.getRuntime().availableProcessors().coerceIn(1, 4)
        return Capacity(offeredBytes = offered, totalBytes = total, threads = threads)
    }
}
