; CyberClean v2.0.0 — Inno Setup Script
; Build: Open this file in Inno Setup Compiler and press Compile
; Download Inno Setup: https://jrsoftware.org/isinfo.php

[Setup]
AppName=CyberClean
AppVersion=2.0.0
AppPublisher=vuphitung
AppPublisherURL=https://github.com/vuphitung/CyberClean
AppSupportURL=https://github.com/vuphitung/CyberClean/issues
AppUpdatesURL=https://github.com/vuphitung/CyberClean/releases
DefaultDirName={autopf}\CyberClean
DefaultGroupName=CyberClean
AllowNoIcons=yes
OutputDir=dist
OutputBaseFilename=CyberClean_Setup_v2.0.0
SetupIconFile=C:\Users\WIN10\Desktop\CyberClean\assets\logo.ico
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
UninstallDisplayName=CyberClean
UninstallDisplayIcon={app}\CyberClean.exe
VersionInfoVersion=2.0.0
VersionInfoDescription=Smart Disk Cleaner

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"

[Files]
Source: "dist\CyberClean.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\CyberClean"; Filename: "{app}\CyberClean.exe"
Name: "{group}\Uninstall CyberClean"; Filename: "{uninstallexe}"
Name: "{userdesktop}\CyberClean";   Filename: "{app}\CyberClean.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\CyberClean.exe"; Description: "Launch CyberClean"; \
    Flags: nowait postinstall skipifsilent runascurrentuser

[UninstallDelete]
; Clean up app data on uninstall
Type: filesandordirs; Name: "{localappdata}\CyberClean"
Type: filesandordirs; Name: "{userappdata}\CyberClean"
