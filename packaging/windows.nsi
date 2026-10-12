Unicode true
Name "Human2API"
OutFile "${OUTFILE}"
InstallDir "$LOCALAPPDATA\Human2API"
RequestExecutionLevel user
Page directory
Page instfiles
UninstPage uninstConfirm
UninstPage instfiles
Section "Human2API Studio and CLI"
  SetOutPath "$INSTDIR"
  File /r "${APPDIR}\*"
  CreateShortcut "$DESKTOP\Human2API Studio.lnk" "$INSTDIR\Human2API-Studio\Human2API-Studio.exe"
  WriteUninstaller "$INSTDIR\Uninstall.exe"
SectionEnd
Section "Uninstall"
  Delete "$DESKTOP\Human2API Studio.lnk"
  RMDir /r "$INSTDIR\Human2API-Studio"
  RMDir /r "$INSTDIR\h2a"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"
  ; User workflows under $PROFILE\Human2API are intentionally preserved.
SectionEnd
