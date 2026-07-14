use std::sync::Mutex;
use tauri::{AppHandle, Manager, RunEvent};
use tauri_plugin_shell::ShellExt;
use tauri_plugin_shell::process::{CommandChild, CommandEvent};

pub struct SidecarState {
    pub child: Mutex<Option<CommandChild>>,
}

pub fn start_sidecar(app: &AppHandle) {
    // In `tauri dev` the bundled backend binary is usually not present — the
    // developer runs `uv run localy serve` in a separate terminal instead.
    // Missing binary must NOT crash the app: log and return so the UI still
    // loads and connects to a separately-running backend on 127.0.0.1:11434.
    let sidecar_command = match app.shell().sidecar("localy-backend") {
        Ok(cmd) => cmd.args(["serve"]),
        Err(e) => {
            eprintln!(
                "⚠️  localy-backend sidecar not found ({e}). \
                 Start the backend manually with `uv run localy serve` \
                 (this is expected in dev mode)."
            );
            return;
        }
    };

    println!("🚀 Spawning localy-backend sidecar...");

    let (mut rx, child) = match sidecar_command.spawn() {
        Ok(pair) => pair,
        Err(e) => {
            eprintln!(
                "⚠️  Failed to spawn localy-backend sidecar ({e}). \
                 Start the backend manually with `uv run localy serve`."
            );
            return;
        }
    };

    // Manage child process state
    app.manage(SidecarState {
        child: Mutex::new(Some(child)),
    });

    // Spawn a background task to read output logs
    tauri::async_runtime::spawn(async move {
        while let Some(event) = rx.recv().await {
            match event {
                CommandEvent::Stdout(line_bytes) => {
                    let line = String::from_utf8_lossy(&line_bytes);
                    print!("[Backend stdout] {}", line);
                }
                CommandEvent::Stderr(line_bytes) => {
                    let line = String::from_utf8_lossy(&line_bytes);
                    eprint!("[Backend stderr] {}", line);
                }
                CommandEvent::Terminated(status) => {
                    println!("[Backend] Terminated with status: {:?}", status.code);
                    break;
                }
                _ => {}
            }
        }
    });
}

pub fn handle_app_exit(app_handle: &AppHandle, event: &RunEvent) {
    if let RunEvent::Exit = event {
        println!("⏹️ Stopping localy-backend sidecar...");
        if let Some(state) = app_handle.try_state::<SidecarState>() {
            if let Ok(mut lock) = state.child.lock() {
                if let Some(child) = lock.take() {
                    match child.kill() {
                        Ok(_) => println!("✅ Sidecar terminated successfully."),
                        Err(e) => eprintln!("❌ Failed to kill sidecar: {}", e),
                    }
                }
            }
        }
    }
}
