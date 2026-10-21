; Inno Setup script — 太阳能供热蓄热设计工具 client installer
; Build: ISCC.exe installer.iss  (portable Inno under D:\tools\inno6\app)
; Payload: dist\SolarHeatingDesign\* produced by build_exe.bat

#define MyAppName "太阳能供热蓄热设计工具"
#define MyAppVersion "1.0.0"
#define MyAppExeName "SolarHeatingDesign.exe"

[Setup]
AppId={{B7F4A9C2-3D5E-4F6A-8B90-1C2D3E4F5A60}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
UninstallDisplayName={#MyAppName}
DefaultDirName={autopf}\SolarHeatingDesign
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=installer
OutputBaseFilename=太阳能供热设计工具安装包
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "dist\SolarHeatingDesign\SolarHeatingDesign.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\SolarHeatingDesign\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "01 input files\*"; DestDir: "{app}\01 input files"; Flags: recursesubdirs createallsubdirs
Source: "design_inputs.xlsx"; DestDir: "{app}"; Flags: ignoreversion
Source: "design_inputs.json"; DestDir: "{app}"; Flags: ignoreversion
Source: "MODEL_DESCRIPTION.md"; DestDir: "{app}"
Source: "OPTIMIZATION_GUIDE.md"; DestDir: "{app}"
Source: "README.md"; DestDir: "{app}"
Source: "不同方案不确定性分析.xlsx"; DestDir: "{app}"
Source: "谢通门新负荷分析.docx"; DestDir: "{app}"

[Dirs]
Name: "{app}\02 reports"; Flags: uninsneveruninstall

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[Messages]
chinesesimplified.WelcomeLabel2=这将会把 [name/ver] 安装到您的电脑。%n%n建议在安装前关闭其他应用程序。
