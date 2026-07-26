use std::process::{Child, Command};
use std::sync::Mutex;
use tauri::{AppHandle, Manager, RunEvent};
use tauri::path::BaseDirectory;

#[cfg(windows)]
use std::os::windows::process::CommandExt;
#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

pub struct SidecarState {
    pub child: Mutex<Option<Child>>,
}

/// Launch the bundled Localy backend (PyInstaller onedir) from app resources.
///
/// The backend needs no Python on the target machine. We also point it at the
/// bundled RPC binaries via LOCALY_LLAMA_BIN_DIR so device pooling works out of
/// the box on a fresh install.
pub fn start_sidecar(app: &AppHandle) {
    let backend_exe = match app
        .path()
        .resolve("resources/backend/localy-backend.exe", BaseDirectory::Resource)
    {
        Ok(p) => p,
        Err(e) => {
            eprintln!("⚠️  Could not resolve backend resource path: {e}");
            return;
        }
    };

    if !backend_exe.exists() {
        eprintln!(
            "⚠️  Bundled backend not found at {}. In dev, run `uv run localy serve` manually.",
            backend_exe.display()
        );
        return;
    }

    // Bundled RPC binaries for pooling (coordinator/worker).
    let rpc_dir = app
        .path()
        .resolve("resources/llama-rpc", BaseDirectory::Resource)
        .ok();

    println!("🚀 Spawning bundled localy-backend: {}", backend_exe.display());

    let mut cmd = Command::new(&backend_exe);
    // Bind 0.0.0.0 so LAN clients and the internet tunnel can reach the API.
    // Non-loopback requests are gated by API key (fail-closed), so this is safe.
    cmd.arg("serve").arg("--host").arg("0.0.0.0");
    if let Some(dir) = &rpc_dir {
        cmd.env("LOCALY_LLAMA_BIN_DIR", dir);
    }
    // The desktop app exposes pool controls as a first-class feature. Enable
    // transparent /v1 chat proxying to a ready pooled coordinator in packaged
    // builds so "Run pooled" actually serves that model from Chat.
    cmd.env("LOCALY_POOL_ENABLED", "true");
    // Run from the backend folder so it finds its _internal deps.
    if let Some(parent) = backend_exe.parent() {
        cmd.current_dir(parent);
    }
    #[cfg(windows)]
    cmd.creation_flags(CREATE_NO_WINDOW);

    match cmd.spawn() {
        Ok(child) => {
            app.manage(SidecarState {
                child: Mutex::new(Some(child)),
            });
            println!("✅ Backend started.");
        }
        Err(e) => eprintln!("⚠️  Failed to spawn backend: {e}"),
    }
}

pub fn handle_app_exit(app_handle: &AppHandle, event: &RunEvent) {
    if let RunEvent::Exit = event {
        println!("⏹️  Stopping localy-backend...");
        if let Some(state) = app_handle.try_state::<SidecarState>() {
            if let Ok(mut lock) = state.child.lock() {
                if let Some(mut child) = lock.take() {
                    // Kill the WHOLE process tree, not just the backend. The
                    // backend spawns children (pooled llama-server coordinator,
                    // cloudflared tunnel, rpc worker) that would otherwise be
                    // orphaned — left holding install-folder files (blocking the
                    // next install) and ports. On Windows, child.kill() only
                    // terminates the single process, so use taskkill /T.
                    #[cfg(windows)]
                    {
                        let pid = child.id();
                        let mut kill = Command::new("taskkill");
                        kill.args(["/F", "/T", "/PID", &pid.to_string()]);
                        kill.creation_flags(CREATE_NO_WINDOW);
                        let _ = kill.status();
                    }
                    let _ = child.kill();
                }
            }
        }
    }
}
