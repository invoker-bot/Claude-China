#ifndef AppVersion
  #error AppVersion must be supplied by tools/build_desktop.py
#endif

[Setup]
AppId=ClaudeChina.DesktopLauncher
AppName=Claude China
AppVersion={#AppVersion}
AppPublisher=Claude China contributors
AppPublisherURL=https://github.com/invoker-bot/Claude-China
AppSupportURL=https://github.com/invoker-bot/Claude-China/issues
AppUpdatesURL=https://github.com/invoker-bot/Claude-China/releases/latest
DefaultDirName={localappdata}\Programs\Claude China
DefaultGroupName=Claude China
DisableProgramGroupPage=auto
AllowNoIcons=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
AppMutex=Local\ClaudeChina.DesktopLauncher
UninstallDisplayIcon={app}\claude-china-desktop.exe
UninstallDisplayName=Claude China
OutputDir={#OutputDirectory}
OutputBaseFilename=Claude-China-{#AppVersion}-windows-x64-setup
SetupIconFile={#IconFile}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "{#BundleDirectory}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#WebViewBootstrapper}"; DestName: "MicrosoftEdgeWebview2Setup.exe"; Flags: dontcopy

[Icons]
Name: "{group}\Claude China"; Filename: "{app}\claude-china-desktop.exe"; AppUserModelID: "ClaudeChina.DesktopLauncher"
Name: "{autodesktop}\Claude China"; Filename: "{app}\claude-china-desktop.exe"; Tasks: desktopicon; AppUserModelID: "ClaudeChina.DesktopLauncher"

[Run]
Filename: "{app}\claude-china-desktop.exe"; Description: "Open Claude China"; Flags: nowait postinstall skipifsilent

[Code]
function HasWebView2: Boolean;
var
  Version: String;
  Key: String;
begin
  Key := 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';
  Result := (RegQueryStringValue(HKCU, Key, 'pv', Version) and
             (Version <> '') and (Version <> '0.0.0.0'));
  if not Result then
    Result := (RegQueryStringValue(HKLM32, Key, 'pv', Version) and
               (Version <> '') and (Version <> '0.0.0.0'));
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ExitCode: Integer;
begin
  Result := '';
  if not HasWebView2 then
  begin
    ExtractTemporaryFile('MicrosoftEdgeWebview2Setup.exe');
    if not Exec(ExpandConstant('{tmp}\MicrosoftEdgeWebview2Setup.exe'),
                '/silent /install', '', SW_HIDE, ewWaitUntilTerminated, ExitCode) then
      Result := 'Could not start Microsoft WebView2 Runtime setup.'
    else if not HasWebView2 then
      Result := 'Microsoft WebView2 Runtime is required. Connect to the internet or install the WebView2 Evergreen Runtime from Microsoft, then run this installer again.';
  end;
end;
