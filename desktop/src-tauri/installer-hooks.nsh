; Localy NSIS installer hooks.
; Before copying files, terminate any running Localy (app + bundled backend +
; pooled coordinator). With the tray/daemon mode a previous instance can keep
; running in the background and hold install-folder DLLs open, which otherwise
; causes "Error opening file for writing" during an upgrade.

!macro NSIS_HOOK_PREINSTALL
  DetailPrint "Stopping any running Localy instance..."
  nsExec::Exec 'taskkill /F /T /IM Localy.exe'
  nsExec::Exec 'taskkill /F /T /IM localy-backend.exe'
  nsExec::Exec 'taskkill /F /T /IM llama-server.exe'
  ; Give Windows a moment to release the file handles before we copy.
  Sleep 1000
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  nsExec::Exec 'taskkill /F /T /IM Localy.exe'
  nsExec::Exec 'taskkill /F /T /IM localy-backend.exe'
  nsExec::Exec 'taskkill /F /T /IM llama-server.exe'
  Sleep 1000
!macroend
