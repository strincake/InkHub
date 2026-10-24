#ifndef AppVersion
  #error AppVersion must be supplied
#endif
[Setup]
AppId={{62F1DA7B-57D4-46CD-893F-7E512B73E798}
AppName=墨枢 InkHub
AppVersion={#AppVersion}
AppPublisher=InkHub Contributors
DefaultDirName={localappdata}\Programs\InkHub
DefaultGroupName=墨枢 InkHub
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.19041
OutputDir={#OutputDir}
OutputBaseFilename=InkHub-{#AppVersion}-windows-x64-setup
SetupIconFile={#SourceDir}\assets\InkHub.ico
UninstallDisplayIcon={app}\InkHub.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
Uninstallable=yes
[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"
[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; Flags: unchecked
[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{autoprograms}\墨枢 InkHub"; Filename: "{app}\InkHub.exe"
Name: "{autodesktop}\墨枢 InkHub"; Filename: "{app}\InkHub.exe"; Tasks: desktopicon
[Run]
Filename: "{app}\InkHub.exe"; Description: "启动墨枢 InkHub（驻留托盘）"; Flags: nowait postinstall skipifsilent

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  CurrentCommand: String;
  OwnedCommand: String;
begin
  if CurUninstallStep = usUninstall then
  begin
    OwnedCommand := '"' + ExpandConstant('{app}\InkHub.exe') + '" --autostart';
    if RegQueryStringValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run',
      'InkHub', CurrentCommand) then
    begin
      if CompareStr(CurrentCommand, OwnedCommand) = 0 then
        RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'InkHub');
    end;
  end;
end;
