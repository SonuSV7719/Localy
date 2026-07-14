package com.localy.worker

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import com.localy.worker.databinding.ActivityMainBinding

/**
 * One screen, one button. Tap Connect → this phone joins the pool and appears
 * automatically on the coordinator's Device Pool screen. No setup.
 */
class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private val handler = Handler(Looper.getMainLooper())

    private val requestNotif =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { /* proceed regardless */ }

    private val poll = object : Runnable {
        override fun run() {
            refreshUi()
            handler.postDelayed(this, 1500)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        val cap = HardwareInfo.capacity(this)
        val offeredGb = cap.offeredBytes / (1024.0 * 1024 * 1024)
        binding.deviceInfo.text = "%s · offering ~%.1f GB RAM · %d threads"
            .format(Build.MODEL, offeredGb, cap.threads)

        binding.connectButton.setOnClickListener {
            if (WorkerService.running) stopWorker() else startWorker()
        }
        binding.manageCacheButton.setOnClickListener {
            startActivity(Intent(this, CacheActivity::class.java))
        }
        refreshUi()
    }

    override fun onResume() {
        super.onResume()
        handler.post(poll)
    }

    override fun onPause() {
        super.onPause()
        handler.removeCallbacks(poll)
    }

    private fun startWorker() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS)
            != PackageManager.PERMISSION_GRANTED
        ) {
            requestNotif.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
        val intent = Intent(this, WorkerService::class.java).apply { action = WorkerService.ACTION_START }
        ContextCompat.startForegroundService(this, intent)
    }

    private fun stopWorker() {
        val intent = Intent(this, WorkerService::class.java).apply { action = WorkerService.ACTION_STOP }
        startService(intent)
    }

    private fun refreshUi() {
        val on = WorkerService.running
        binding.connectButton.text = if (on) "Disconnect" else "Connect"
        binding.statusText.text = if (on) WorkerService.statusText else "Not connected"
        binding.statusDot.setBackgroundResource(
            if (on) android.R.drawable.presence_online else android.R.drawable.presence_invisible
        )
    }
}
