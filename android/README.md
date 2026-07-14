# Localy Worker (Android)

Zero-setup pool worker for Phase 3. Your friend installs this APK, taps
**Connect**, and their phone joins the pool automatically — no Termux, no
command line. It bundles a native `ggml-rpc-server` (llama.cpp RPC backend,
cross-compiled for ARM64) and advertises itself over mDNS so the desktop
coordinator discovers it on the same WiFi/hotspot.

## How it works
- `libggml-rpc-server.so` in `app/src/main/jniLibs/arm64-v8a/` is the real
  llama.cpp `ggml-rpc-server` executable (packaged as a `.so` so Android lets us
  run it from the app's native lib dir). Build it with
  `scripts/build-android-rpc.bat` from the repo root.
- `RpcWorker` execs it as a child process (`--host 0.0.0.0 --port 50052`).
- `NsdAdvertiser` registers `_localy._tcp` over mDNS with the device's offered
  RAM, matching what the desktop coordinator's discovery browser expects.
- `WorkerService` keeps it alive as a foreground service with a wake lock.

## Build the APK

Prerequisites: Android SDK + NDK (r27), JDK 17+ (Android Studio's JBR works).

**Option A — Android Studio (easiest):** open the `android/` folder, let Gradle
sync, then Run ▶ onto a connected phone.

**Option B — command line:**
```bash
# 1. Build the native ARM64 worker binary (once):
scripts\build-android-rpc.bat
# 2. Build the APK:
cd android
./gradlew :app:assembleDebug
# APK at: app/build/outputs/apk/debug/app-debug.apk
```

## Install on a phone
```bash
adb install -r app/build/outputs/apk/debug/app-debug.apk
```
Or copy the APK to the phone and open it (allow "install from unknown sources").

## Use it
1. Phone and PC on the **same WiFi or hotspot**.
2. Open **Localy Worker** on the phone → tap **Connect**.
3. On the PC, open Localy → **Device Pool** → the phone appears automatically
   (or `localy pool discover`).

## Honest note
A phone is a slow node — it lets a friend join in one tap, but the real speed
win in a pool comes from actual computers. Zero-setup fixes the UX, not the
physics.
