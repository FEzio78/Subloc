; Inno Setup script for the Windows installer (run by tools/build.py: ISCC /DAppVersion=x.y.z installer\subloc.iss).
; Packs dist\Subloc (the PyInstaller build) into dist\Subloc-<version>-setup.exe.
; Per-user install, no admin rights. Models and settings live in %LOCALAPPDATA%\Subloc (downloaded by Setup on
; first launch), not in the program folder.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
; Never change AppId: Windows uses it to recognise updates of the same app.
AppId={{362BE564-7587-4085-AFF1-A8AC4B5EF4C2}
AppName=Subloc
AppVersion={#AppVersion}
AppVerName=Subloc {#AppVersion}
AppPublisher=Subloc
AppPublisherURL=https://github.com/FEzio78/Subloc
AppSupportURL=https://github.com/FEzio78/Subloc/issues
AppUpdatesURL=https://github.com/FEzio78/Subloc/releases
DefaultDirName={autopf}\Subloc
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=Subloc-{#AppVersion}-setup
SetupIconFile=..\subloc\assets\icon.ico
UninstallDisplayIcon={app}\Subloc.exe
UninstallDisplayName=Subloc
WizardStyle=modern
Compression=lzma2/ultra64
SolidCompression=yes
; A big window lets the compressor see that ffprobe.exe repeats most of ffmpeg.exe (and other repeats).
LZMADictionarySize=262144
LZMANumFastBytes=273
LZMAUseSeparateProcess=yes
ShowLanguageDialog=auto
ChangesAssociations=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "arabic"; MessagesFile: "compiler:Languages\Arabic.isl"

[CustomMessages]
english.MakeSubtitles=Make subtitles with Subloc
arabic.MakeSubtitles=اصنع ترجمة باستخدام Subloc
english.ExplorerMenu=Add "Make subtitles with Subloc" to the right-click menu of videos and folders
arabic.ExplorerMenu=أضف "اصنع ترجمة باستخدام Subloc" إلى قائمة النقر بزر الفأرة الأيمن للمقاطع والمجلدات
english.RemoveData=Also delete Subloc's downloaded models and settings?%n%nThey are in %1 and can take several GB. Keep them if you plan to install Subloc again.
arabic.RemoveData=هل تريد أيضًا حذف النماذج التي نزّلها Subloc وإعداداته؟%n%nهي في %1 وقد تشغل عدة غيغابايت. أبقِها إن كنت ستثبّت Subloc مرة أخرى.

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "explorermenu"; Description: "{cm:ExplorerMenu}"

[InstallDelete]
; An update replaces the whole program folder's libraries: files an older version had and this one doesn't would
; otherwise stay next to the new ones (a packaged Python app can then load the wrong one). Data is elsewhere
; (%LOCALAPPDATA%\Subloc) and is never touched here.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\Subloc\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; The GPL needs no "I accept" page (it covers copying and changing the program, not using it): the licence and the
; third-party notices are installed next to the app instead.
Source: "..\LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"
Source: "..\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"

[Icons]
Name: "{autoprograms}\Subloc"; Filename: "{app}\Subloc.exe"
Name: "{autodesktop}\Subloc"; Filename: "{app}\Subloc.exe"; Tasks: desktopicon

[Registry]
; "Make subtitles with Subloc" on videos and folders (per user; removed on uninstall).
#define VideoMenu(Ext) \
  'Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\' + Ext + '\shell\Subloc"; ValueType: string; ValueName: ""; ValueData: "{cm:MakeSubtitles}"; Flags: uninsdeletekey; Tasks: explorermenu' + NewLine + \
  'Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\' + Ext + '\shell\Subloc"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\Subloc.exe"; Tasks: explorermenu' + NewLine + \
  'Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\' + Ext + '\shell\Subloc\command"; ValueType: string; ValueName: ""; ValueData: """{app}\Subloc.exe"" ""%1"""; Tasks: explorermenu' + NewLine
#emit VideoMenu(".mp4")
#emit VideoMenu(".mkv")
#emit VideoMenu(".avi")
#emit VideoMenu(".mov")
#emit VideoMenu(".webm")
#emit VideoMenu(".m4v")
#emit VideoMenu(".ts")
#emit VideoMenu(".wmv")
Root: HKCU; Subkey: "Software\Classes\Directory\shell\Subloc"; ValueType: string; ValueName: ""; ValueData: "{cm:MakeSubtitles}"; Flags: uninsdeletekey; Tasks: explorermenu
Root: HKCU; Subkey: "Software\Classes\Directory\shell\Subloc"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\Subloc.exe"; Tasks: explorermenu
Root: HKCU; Subkey: "Software\Classes\Directory\shell\Subloc\command"; ValueType: string; ValueName: ""; ValueData: """{app}\Subloc.exe"" ""%1"""; Tasks: explorermenu

[Run]
Filename: "{app}\Subloc.exe"; Description: "{cm:LaunchProgram,Subloc}"; Flags: nowait postinstall skipifsilent

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Data: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    Data := ExpandConstant('{localappdata}\Subloc');
    if DirExists(Data) and not UninstallSilent then
      if MsgBox(FmtMessage(CustomMessage('RemoveData'), [Data]), mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(Data, True, True, True);
  end;
end;
