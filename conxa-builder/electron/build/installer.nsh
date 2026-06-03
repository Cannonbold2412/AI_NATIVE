; Custom NSIS macros for Conxa Build Studio installer.
; Included by electron-builder via nsis.include in electron-builder.yml.

!macro customInstall
  ; Registry keys so IT can detect the installed version.
  WriteRegStr HKLM "Software\Conxa\BuildStudio" "Version" "${VERSION}"
  WriteRegStr HKLM "Software\Conxa\BuildStudio" "InstallPath" "$INSTDIR"

  ; Register conxa-studio:// URI scheme for OAuth callbacks.
  WriteRegStr HKCR "conxa-studio" "" "URL:Conxa Studio Protocol"
  WriteRegStr HKCR "conxa-studio" "URL Protocol" ""
  WriteRegStr HKCR "conxa-studio\shell\open\command" "" '"$INSTDIR\Conxa Build Studio.exe" "%1"'
!macroend

!macro customUninstall
  ; --- Remove registry entries added during install ---
  DeleteRegKey HKLM "Software\Conxa\BuildStudio"
  DeleteRegKey HKCR "conxa-studio"

  ; --- Two-tier data removal ---
  ; By default we keep user data (~\.conxa\) so that recorded sessions,
  ; compiled skills, and cached packages survive a reinstall or upgrade.
  ; Enterprise IT can tick the checkbox to wipe everything (offboarding).

  ; Resolve %USERPROFILE%\.conxa — expand the env var at uninstall time.
  ReadEnvStr $0 USERPROFILE
  StrCpy $1 "$0\.conxa"

  ; Ask only when the data directory actually exists.
  IfFileExists "$1\*.*" askUser skipAsk

  askUser:
    MessageBox MB_YESNO|MB_ICONQUESTION \
      "Do you also want to delete your Conxa data?$\r$\n$\r$\n\
$1$\r$\n$\r$\n\
This includes recorded sessions, compiled skills, and local caches.$\r$\n\
Leave this data if you plan to reinstall or upgrade Conxa Build Studio.$\r$\n$\r$\n\
Click YES to delete, NO to keep." \
      IDYES deleteData IDNO skipAsk

  deleteData:
    RMDir /r "$1"

  skipAsk:
!macroend
