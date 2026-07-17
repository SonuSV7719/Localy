mod sidecar;

use std::sync::atomic::{AtomicBool, Ordering};
use tauri::{
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    Manager, WindowEvent,
};

/// User setting: when true, closing the window keeps the backend running in
/// the system tray instead of quitting. Stored here so the Rust window-close
/// handler can read it; the frontend keeps it in sync via `set_run_in_background`.
pub struct RunInBackground(pub AtomicBool);

#[tauri::command]
fn set_run_in_background(state: tauri::State<RunInBackground>, enabled: bool) {
    state.0.store(enabled, Ordering::Relaxed);
}

/// Fully quit the app (kills the backend sidecar via the Exit handler).
#[tauri::command]
fn quit_app(app: tauri::AppHandle) {
    app.exit(0);
}

/// Bring the main window to the foreground (used by the tray "Open" action).
fn show_main_window(app: &tauri::AppHandle) {
    if let Some(win) = app.get_webview_window("main") {
        let _ = win.show();
        let _ = win.unminimize();
        let _ = win.set_focus();
    }
}

fn build_tray(app: &tauri::AppHandle) -> tauri::Result<()> {
    let open = MenuItem::with_id(app, "open", "Open Localy", true, None::<&str>)?;
    let quit = MenuItem::with_id(app, "quit", "Stop backend & quit", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&open, &quit])?;

    TrayIconBuilder::with_id("localy-tray")
        .icon(app.default_window_icon().unwrap().clone())
        .tooltip("Localy — local AI server running")
        .menu(&menu)
        .show_menu_on_left_click(false)
        .on_menu_event(|app, event| match event.id.as_ref() {
            "open" => show_main_window(app),
            "quit" => app.exit(0),
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            // Left-click the tray icon to reopen the window.
            if let TrayIconEvent::Click {
                button: MouseButton::Left,
                button_state: MouseButtonState::Up,
                ..
            } = event
            {
                show_main_window(tray.app_handle());
            }
        })
        .build(app)?;
    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let mut builder = tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_shell::init());

    // Autostart-on-login (desktop only). Toggled from the frontend Settings.
    #[cfg(desktop)]
    {
        builder = builder.plugin(tauri_plugin_autostart::init(
            tauri_plugin_autostart::MacosLauncher::LaunchAgent,
            None,
        ));
    }

    builder
        .manage(RunInBackground(AtomicBool::new(false)))
        .invoke_handler(tauri::generate_handler![set_run_in_background, quit_app])
        .setup(|app| {
            sidecar::start_sidecar(app.handle());
            build_tray(app.handle())?;
            Ok(())
        })
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { api, .. } = event {
                let app = window.app_handle();
                let keep_running = app
                    .state::<RunInBackground>()
                    .0
                    .load(Ordering::Relaxed);
                if keep_running {
                    // Hide to tray instead of quitting; backend keeps serving.
                    api.prevent_close();
                    let _ = window.hide();
                }
            }
        })
        .build(tauri::generate_context!())
        .expect("error while running tauri application")
        .run(|app_handle, event| {
            sidecar::handle_app_exit(app_handle, &event);
        });
}
