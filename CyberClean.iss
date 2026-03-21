; CyberClean v2.0.0 - Inno Setup Script
; Build: Open in Inno Setup Compiler and press Compile (F9)
; Download: https://jrsoftware.org/isinfo.php

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
; Shortcuts call schtasks to run the hidden Task - no UAC prompt on launch
Name: "{group}\CyberClean"; Filename: "schtasks"; Parameters: "/run /tn ""CyberClean_AutoAdmin"""; IconFilename: "{app}\CyberClean.exe"
Name: "{group}\Uninstall CyberClean"; Filename: "{uninstallexe}"
Name: "{userdesktop}\CyberClean"; Filename: "schtasks"; Parameters: "/run /tn ""CyberClean_AutoAdmin"""; IconFilename: "{app}\CyberClean.exe"; Tasks: desktopicon

[Run]
; Create hidden Task with highest privilege - this is the ONE-TIME UAC moment
Filename: "schtasks"; Parameters: "/create /tn ""CyberClean_AutoAdmin"" /tr ""'{app}\CyberClean.exe'"" /sc onlogon /rl highest /f"; Flags: runhidden waituntilterminated
; Launch via Task right after install (no UAC)
Filename: "schtasks"; Parameters: "/run /tn ""CyberClean_AutoAdmin"""; Description: "Launch CyberClean"; Flags: nowait postinstall skipifsilent runhidden

[UninstallRun]
; Remove the hidden Task on uninstall
Filename: "schtasks"; Parameters: "/delete /tn ""CyberClean_AutoAdmin"" /f"; Flags: runhidden waituntilterminated

[UninstallDelete]
Type: filesandordirs; Name: "{localappdata}\CyberClean"
Type: filesandordirs; Name: "{userappdata}\CyberClean"
