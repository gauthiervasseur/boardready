; Inno Setup script for BoardReady. Built by build_exe.ps1, which passes the three defines.
; Installs for the current user only (no administrator rights needed).
#ifndef SourceDir
  #define SourceDir "dist\BoardReady"
#endif
#ifndef OutputDir
  #define OutputDir "dist"
#endif
#define AppName "BoardReady"
#define AppVersion "1.0"

[Setup]
AppId={{6B0F3C1E-5E0B-4B6B-9F5B-0B0A2D7C1A11}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Data Wise Academy
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir={#OutputDir}
OutputBaseFilename=BoardReady-Setup
#ifdef IconFile
SetupIconFile={#IconFile}
#endif
UninstallDisplayIcon={app}\{#AppName}.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppName}.exe"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppName}.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Run]
Filename: "{app}\{#AppName}.exe"; Description: "Start {#AppName}"; Flags: nowait postinstall skipifsilent
