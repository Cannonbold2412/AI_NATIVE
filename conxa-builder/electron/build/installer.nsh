; installer.nsh — custom NSIS macros included by electron-builder
; Registers the conxa-studio:// URI scheme for Clerk OAuth callbacks.

!macro customInstall
  ; Register conxa-studio:// custom URI scheme
  WriteRegStr HKCU "Software\Classes\conxa-studio" "" "URL:Conxa Studio Protocol"
  WriteRegStr HKCU "Software\Classes\conxa-studio" "URL Protocol" ""
  WriteRegStr HKCU "Software\Classes\conxa-studio\DefaultIcon" "" "$INSTDIR\Conxa Build Studio.exe,0"
  WriteRegStr HKCU "Software\Classes\conxa-studio\shell" "" ""
  WriteRegStr HKCU "Software\Classes\conxa-studio\shell\open" "" ""
  WriteRegStr HKCU "Software\Classes\conxa-studio\shell\open\command" "" '"$INSTDIR\Conxa Build Studio.exe" "%1"'
!macroend

!macro customUninstall
  ; Remove conxa-studio:// URI scheme registration
  DeleteRegKey HKCU "Software\Classes\conxa-studio"
!macroend
