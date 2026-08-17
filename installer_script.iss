; Garmin Chat Desktop v4.0.4 Installer Script
; Inno Setup 6.x Required
; This script creates a professional Windows installer

#define MyAppName "Garmin Chat Desktop"
#define MyAppVersion "4.0.4"
#define MyAppPublisher "Rod Trent"
#define MyAppURL "https://github.com/rod-trent/GarminChatDesktop"
#define MyAppExeName "GarminChatDesktop.exe"
#define MyAppAssocName MyAppName + " Chat File"
#define MyAppAssocExt ".gchat"
#define MyAppAssocKey StringChange(MyAppAssocName, " ", "") + MyAppAssocExt

[Setup]
; NOTE: Generate a new GUID for your application
; You can generate one at https://www.guidgenerator.com/
AppId={{8F7C9A4B-2E1D-4F3A-9B8C-5D6E7F8A9B0C}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
LicenseFile=LICENSE.txt
; Uncomment the following line if you want to show README during install
; InfoBeforeFile=README.md
OutputDir=.
OutputBaseFilename=GarminChatSetup_v{#MyAppVersion}
SetupIconFile=logo.ico
Compression=lzma2/ultra64
InternalCompressLevel=ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes
LZMADictionarySize=1048576
LZMANumFastBytes=273
WizardStyle=modern
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
; Minimum Windows version (Windows 10)
MinVersion=10.0
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
VersionInfoVersion={#MyAppVersion}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} Installer
VersionInfoCopyright=Copyright (C) 2025 {#MyAppPublisher}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "quicklaunchicon"; Description: "{cm:CreateQuickLaunchIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked; OnlyBelowVersion: 6.1; Check: not IsAdminInstallMode

[Files]
; Main application files
Source: "dist\GarminChatDesktop\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Documentation
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion isreadme
Source: "CHANGELOG.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "INSTALLATION_GUIDE.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "OLLAMA_SETUP_GUIDE.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "LICENSE.txt"; DestDir: "{app}"; Flags: ignoreversion
; NOTE: Don't use "Flags: ignoreversion" on any shared system files

[Icons]
; Start Menu
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:ProgramOnTheWeb,{#MyAppName}}"; Filename: "{#MyAppURL}"
Name: "{group}\Documentation\README"; Filename: "{app}\README.md"
Name: "{group}\Documentation\Installation Guide"; Filename: "{app}\INSTALLATION_GUIDE.md"
Name: "{group}\Documentation\Ollama Setup Guide"; Filename: "{app}\OLLAMA_SETUP_GUIDE.md"
Name: "{group}\Documentation\Changelog"; Filename: "{app}\CHANGELOG.md"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"

; Desktop Icon (optional, user choice)
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

; Quick Launch (for older Windows versions)
Name: "{userappdata}\Microsoft\Internet Explorer\Quick Launch\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: quicklaunchicon

[Run]
; Option to launch application after installation
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[Registry]
; File association (optional - for .gchat files)
Root: HKA; Subkey: "Software\Classes\{#MyAppAssocExt}\OpenWithProgids"; ValueType: string; ValueName: "{#MyAppAssocKey}"; ValueData: ""; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\{#MyAppAssocKey}"; ValueType: string; ValueName: ""; ValueData: "{#MyAppAssocName}"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\{#MyAppAssocKey}\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExeName},0"
Root: HKA; Subkey: "Software\Classes\{#MyAppAssocKey}\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""
Root: HKA; Subkey: "Software\Classes\Applications\{#MyAppExeName}\SupportedTypes"; ValueType: string; ValueName: ".gchat"; ValueData: ""

[Code]
// Custom code for installer behavior

// Check if .NET Framework 4.7.2 or higher is installed (required for some features)
function IsDotNetInstalled: Boolean;
var
  Exists: Boolean;
  Release: Cardinal;
begin
  // Check for .NET 4.7.2 or higher (Release >= 461808)
  Exists := RegQueryDWordValue(HKLM, 'SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full', 'Release', Release);
  Result := Exists and (Release >= 461808);
end;

// Display warning if .NET not installed
function InitializeSetup: Boolean;
begin
  Result := True;
  if not IsDotNetInstalled then
  begin
    if MsgBox('.NET Framework 4.7.2 or higher is recommended for optimal performance.' + #13#10 + 
              'The application may still work, but some features might not be available.' + #13#10#13#10 + 
              'Do you want to continue installation?', 
              mbConfirmation, MB_YESNO) = IDNO then
      Result := False;
  end;
end;

// Custom welcome message
function UpdateReadyMemo(Space, NewLine, MemoUserInfoInfo, MemoDirInfo, MemoTypeInfo,
  MemoComponentsInfo, MemoGroupInfo, MemoTasksInfo: String): String;
var
  S: String;
begin
  // Standard info
  S := '';
  S := S + 'Destination:' + NewLine;
  S := S + Space + MemoDirInfo + NewLine + NewLine;
  
  if MemoTasksInfo <> '' then
  begin
    S := S + 'Additional tasks:' + NewLine;
    S := S + Space + MemoTasksInfo + NewLine + NewLine;
  end;
  
  // Custom message about AI providers
  S := S + 'After installation:' + NewLine;
  S := S + Space + '• Configure your Garmin Connect credentials' + NewLine;
  S := S + Space + '• Choose an AI provider (Ollama is free!)' + NewLine;
  S := S + Space + '• See OLLAMA_SETUP_GUIDE.md for local AI setup' + NewLine;
  
  Result := S;
end;

// Clean up user data on uninstall (optional - ask user)
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  UserDataPath: String;
  ResultCode: Integer;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    UserDataPath := ExpandConstant('{userappdata}\.garmin_chat');
    if DirExists(UserDataPath) then
    begin
      if MsgBox('Do you want to remove all saved chats and settings?' + #13#10 + 
                'This will delete all your conversation history and configuration.' + #13#10#13#10 + 
                'Location: ' + UserDataPath, 
                mbConfirmation, MB_YESNO) = IDYES then
      begin
        DelTree(UserDataPath, True, True, True);
      end;
    end;
  end;
end;

[UninstallDelete]
; Clean up any generated files
Type: filesandordirs; Name: "{app}\*.log"
Type: filesandordirs; Name: "{app}\*.tmp"

[Messages]
; Custom messages
WelcomeLabel2=This will install [name/ver] on your computer.%n%nGarmin Chat Desktop lets you analyze your Garmin Connect fitness data using AI. Choose from cloud providers or run Ollama locally for free, unlimited queries with complete privacy.%n%nIt is recommended that you close all other applications before continuing.
FinishedHeadingLabel=Completing [name] Setup
FinishedLabelNoIcons=Setup has finished installing [name] on your computer.%n%nNext steps:%n• Launch the application%n• Configure your Garmin credentials%n• Select your AI provider%n• For free local AI, see OLLAMA_SETUP_GUIDE.md
