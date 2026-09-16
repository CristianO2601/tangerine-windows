; ---------------------------------------------------------------------------
; Tangerine for Windows - Inno Setup 6 installer script
;
; Compile from anywhere (OutputDir is relative to this file):
;     ISCC.exe /DAPPVER=1.5.0 packaging\installer.iss
;
; Requires the PyInstaller onedir output in ..\dist\Tangerine\ (produced by
; packaging\build.ps1). APPVER defaults to "0.0.0" when not defined on the
; command line.
;
; NOTE: the macro is APPVER, not VER: ISPP already reserves VER for the
; compiler version (ISPPBuiltins.iss does `#if VER >= 0x03000000`), so a
; command-line /DVER=<x.y.z> breaks preprocessing before this script runs.
; ---------------------------------------------------------------------------

#ifndef APPVER
  #define APPVER "0.0.0"
#endif

#define AppName "Tangerine for Windows"
#define AppPublisher "Tangerine for Windows contributors"
#define AppExeName "Tangerine.exe"

[Setup]
; Stable AppId so upgrades replace the previous install instead of stacking.
AppId={{6F1A9C2E-4B7D-4E8A-9C3F-2D5B8A1E7C40}
AppName={#AppName}
AppVersion={#APPVER}
AppVerName={#AppName} {#APPVER}
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\Programs\Tangerine
DefaultGroupName=Tangerine
DisableProgramGroupPage=yes
; "lowest" = per-user install, no UAC prompt, no admin rights required.
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=Tangerine-{#APPVER}-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#AppExeName}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "autostart"; Description: "Start Tangerine automatically when I sign in to Windows"; GroupDescription: "Startup:"

[Files]
Source: "..\dist\Tangerine\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Tangerine"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\Tangerine"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon
Name: "{userstartup}\Tangerine"; Filename: "{app}\{#AppExeName}"; Tasks: autostart

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,Tangerine for Windows}"; Flags: nowait postinstall skipifsilent
