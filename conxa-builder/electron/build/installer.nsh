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
  DeleteRegKey HKLM "Software\Conxa\BuildStudio"
  DeleteRegKey HKCR "conxa-studio"
!macroend
