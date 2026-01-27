; Inno Setup Script for EDGY Repository Modeller Beta v0.1
; This script creates a Windows installer for non-technical users
; Requires Inno Setup Compiler (https://jrsoftware.org/isinfo.php)

[Setup]
AppName=EDGY Repository Modeller
AppVersion=0.1.0
AppVerName=EDGY Repository Modeller Beta v0.1
AppPublisher=EDGY
AppPublisherURL=
AppSupportURL=
AppUpdatesURL=
DefaultDirName={autopf}\EDGY Repository Modeller
DefaultGroupName=EDGY Repository Modeller
AllowNoIcons=yes
LicenseFile=
OutputDir=installer
OutputBaseFilename=EDGY_Repository_Modeller_Beta_v0.1_Setup
SetupIconFile=
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "quicklaunchicon"; Description: "{cm:CreateQuickLaunchIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked; OnlyBelowVersion: 6.1; Check: not IsAdminInstallMode

[Files]
Source: "dist\EDGY_Repository_Modeller_Beta_v0.1.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "README_BETA.md"; DestDir: "{app}"; Flags: ignoreversion isreadme
; Note: Don't use "Flags: ignoreversion" on any shared system files

[Icons]
Name: "{group}\EDGY Repository Modeller"; Filename: "{app}\EDGY_Repository_Modeller_Beta_v0.1.exe"
Name: "{group}\{cm:UninstallProgram,EDGY Repository Modeller}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\EDGY Repository Modeller"; Filename: "{app}\EDGY_Repository_Modeller_Beta_v0.1.exe"; Tasks: desktopicon
Name: "{userappdata}\Microsoft\Internet Explorer\Quick Launch\EDGY Repository Modeller"; Filename: "{app}\EDGY_Repository_Modeller_Beta_v0.1.exe"; Tasks: quicklaunchicon

[Run]
Filename: "{app}\EDGY_Repository_Modeller_Beta_v0.1.exe"; Description: "{cm:LaunchProgram,EDGY Repository Modeller}"; Flags: nowait postinstall skipifsilent

[Code]
function InitializeSetup(): Boolean;
begin
  Result := True;
  // Check if .NET Framework or other prerequisites are needed
  // For PyInstaller EXE, no prerequisites are needed as Python is bundled
end;
