; muezzin: the Windows installer. One file, double-clicked, Next until it is
; over: the service is registered, the page answers, and the household's
; folders are where they will stay.
;
; build.ps1 compiles this; it does not have to be run by hand. When it is
; (ISCC muezzin-setup.iss from this folder), the defaults below take you to
; the same place.
;
; What this script promises:
;
;   * the program goes to Program Files and is disposable; the profile, the
;     audio and the logs go to %ProgramData%\muezzin and are never touched by
;     an install, an upgrade or an uninstall — same split as the container's
;     ./config and ./media mounts;
;   * an existing profile is never overwritten, and a UAT profile found in a
;     checkout is offered for migration rather than silently copied;
;   * an uninstall, and an upgrade, finish with no muezzin process holding the
;     install folder. That is a promise and not an assumption: on the first
;     machine this shipped to, the service reported "stopped successfully" and
;     its process was still there seventeen minutes later, so the uninstaller
;     deleted the service definition and its own uninstaller and left behind
;     exactly the two exes the live process had open - and the next install
;     could not copy over them. See SweepOwnProcesses;
;   * the page has no login, so the firewall rules open to the local subnet
;     only. That is a different boundary from a network profile, and it is the
;     measured reason for using it: on the machine this was built for, Windows
;     had filed both adapters as Public, so a Private-only rule let speakers be
;     found, added and handed a URL they could not fetch — a silent house with
;     nothing wrong in it. SECURITY.md is the threat model for anyone who puts
;     8020 on a network they do not control;
;   * pc_speakers is out of scope by design: this program is not meant to
;     drive the speakers of the machine it runs on, on a schedule. Cast, LAN
;     boxes and file outputs are what an installation here is for.
;
; One note for whoever edits this next: comments belong outside the sections
; or on their own lines. The first version of this file carried a trailing
; comment on a [Setup] line and Inno read it as part of the value —
; "PrivilegesRequired is invalid", at line 41, with nothing to say about the
; semicolon. Inno's own [Setup] section supports no inline comments at all.
;
; The second note, learned from a tester's screen rather than from the
; compiler: {app} does not exist until the folder page has been answered. A
; [Code] call that expands it earlier — in InitializeWizard, which runs before
; the first page is drawn — aborts the whole wizard with "Runtime error:
; Internal error: An attempt was made to expand the 'app' constant before it
; was initialized", and the message names no line of this file. It was
; reproduced here in a three-line installer whose only job was to ask for
; {app} in InitializeWizard, so the cause is measured, not inferred. Anything
; that needs the install folder lives in PrepareToInstall (see the note there:
; the pre-install step of CurStepChanged is accepted by the compiler and never
; sent) and later, where {app} is a real path.

#define MyAppName      "muezzin"
; build.ps1 passes /DVersion=..., version and candidate number both, the same string
; it stamps into the exe, so the file never names a build the code contradicts.
#ifndef Version
  #define Version "0.0.0-dev"
#endif
#ifndef StageDir
  #define StageDir AddBackslash(SourcePath) + "stage"
#endif

[Setup]
AppId={{8B7C0B3E-4F44-4E28-B139-6F0D6A2D0F0D}
AppName={#MyAppName}
AppVersion={#Version}
AppPublisher=124c41pl
DefaultDirName={autopf}\muezzin
DefaultGroupName={#MyAppName}
UninstallDisplayIcon={app}\muezzin.exe
; The setup program's own picture. Inno stamps its default installer icon when this line
; is absent, so a build sitting in somebody's Downloads folder wears a generic box with
; someone else's arrow on it. The name is relative to this file, the way LicenseFile below
; is, and it is the same .ico the spec hands PyInstaller. The Start Menu entry and the
; Programs and Features entry are not covered by it: they ask the installed exe for its
; picture, and that exe has the same one in its own resources now.
SetupIconFile=muezzin.ico
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible
Compression=lzma2/max
SolidCompression=yes
OutputDir=dist
OutputBaseFilename=muezzin-{#Version}-setup
LicenseFile=..\..\LICENSE
DisableProgramGroupPage=yes
DisableReadyPage=yes
DisableWelcomePage=no
WizardStyle=modern
; Always write the setup log, without being asked and even when nobody thought
; to pass /LOG. Two of this installer's failure modes are invisible otherwise:
; whether the old service was taken down before the copy, and how many processes
; were holding the install folder when the sweep ran. The file lands in the
; installing user's %TEMP% as "Setup Log <date> #<n>.txt", which is where the
; checklist rows point a person instead of asking them to reproduce from a
; command line.
SetupLogging=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

; No [Tasks] section: the built-in tasks page cannot be hidden when there is
; nothing to migrate, so the two migration ticks are checkboxes on a custom
; page in [Code] instead. A page that asks about nothing is worse than a page
; that does not exist.

[Dirs]
; The folders that outlive the program, created before the service starts, so
; a first start with no profile lands here and not under System32 - where a
; Windows service's default working directory is.
Name: "{commonappdata}\muezzin"
Name: "{commonappdata}\muezzin\media"
Name: "{commonappdata}\muezzin\out"

[Files]
; The payload: the frozen app, the service wrapper (renamed at install time,
; because WinSW manages the service whose name it wears), and the service
; definition next to it.
Source: "{#StageDir}\muezzin.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#StageDir}\WinSW-x64.exe"; DestDir: "{app}"; DestName: "muezzin-service.exe"; Flags: ignoreversion
Source: "{#StageDir}\muezzin-service.xml"; DestDir: "{app}"; Flags: ignoreversion
; The documents, so the machine that runs the service also holds the words
; that say what is safe to expose and what each licence asks.
Source: "..\..\LICENSE"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "..\..\README.md"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "..\..\SECURITY.md"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "..\..\THIRD-PARTY.md"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "..\..\config\README.md"; DestDir: "{app}\docs\profile"; Flags: ignoreversion
; Migration is done in [Code], not here: a [Files] entry cannot name a source
; chosen at run time ({code:} is for destinations only, and the compiler says
; so). What a tick copies is written down in MigrateConfig and MigrateMedia.

[Code]
var
  ConfigFrom: String;   // a profile found in a checkout, "" when there is none
  MediaFrom: String;    // its media folder, "" when that folder is not there
  CarriedAccount: AnsiString;  // a <serviceaccount> block read off the previous install
  LogonPage: TInputQueryWizardPage;
  MigrationPage: TInputOptionWizardPage;
  UninstallHeld: Integer;      // processes still holding {app} when the uninstall ran
  UninstallLogsLeft: Integer;  // the service's own log files that would not delete

function ConfigSource(): String;
begin
  Result := ConfigFrom;
end;

function ServiceExe(): String;
begin
  Result := ExpandConstant('{app}\muezzin-service.exe');
end;

function ServiceDefinition(): String;
begin
  Result := ExpandConstant('{app}\muezzin-service.xml');
end;

function SweepOwnProcesses(const why: String): Integer;
var
  resultCode, endedCount, stillThere: Integer;
  appDir, psCmd: String;
begin
  // Wait for the program's own processes to let go of the install folder, end
  // them if they will not, and report how many are still there.
  //
  // This exists because of a measurement, not a theory. On the first machine
  // this shipped to, the uninstaller asked the wrapper to stop at
  // 20:49:55.797 and the wrapper wrote "Service ... stopped successfully"; the
  // service's own stop action ran (its taskkill helper shows up as pid 32080)
  // and WinSW logged "WaitForProcessToExit 21072+32080"; 450 ms later the
  // uninstall step wrote "WARN - Service ... is started. It may be impossible
  // to uninstall it"; and the last line of that wrapper log, "Finished
  // muezzin", is stamped 21:06:45 - seventeen minutes after the stop was asked
  // for. In between, the uninstaller deleted the service definition, its own
  // uninstaller and everything else it could reach, and left behind two files:
  // muezzin.exe and muezzin-service.exe, the two a live process holds open.
  // Installing again then failed on a file in use.
  //
  // So what has to be waited for is the process, not the service control
  // manager's answer, and not the taskkill line in the service definition,
  // whose effect in that sequence could not be confirmed from any log. Twelve
  // half-second peeks give a well-behaved process six seconds to leave on its
  // own before it is ended, and what happened comes back in the exit code,
  // because the exit code of that one process is the only channel between the
  // check and the log: the number ended, times a thousand, plus the number
  // still there. The caller unpacks it and says so out loud, instead of leaving
  // the next person to work it out from a file that would not delete.
  //
  // A process is "mine" if its image name starts with muezzin and its image
  // path is under this install folder. A process whose image path Windows will
  // not name to this session counts as well, because that is what a service
  // running under another account looks like from here; the price is that such
  // a daemon, started by hand from a source checkout, gets ended too. A muezzin
  // running out of some other folder is left alone either way.
  appDir := ExpandConstant('{app}');
  // Single quotes only, and no double quote anywhere in the command: the whole
  // thing is wrapped in one pair for powershell -Command, and a nested one
  // would end the argument there. The name test is done in PowerShell rather
  // than in a WQL filter for the same reason - the filter would want quotes.
  psCmd :=
    '$ErrorActionPreference=''SilentlyContinue'';' +
    '$dir=''' + appDir + ''';' +
    '$killed = 0;' +
    'function Get-Mine { @(Get-CimInstance Win32_Process | Where-Object {' +
      '($_.Name -like ''muezzin*'') -and ' +
      '(($_.ExecutablePath -like ($dir+''\*'')) -or ($null -eq $_.ExecutablePath)) }) };' +
    'for ($i = 0; $i -lt 12; $i++) { if ((Get-Mine).Count -eq 0) { break };' +
    ' Start-Sleep -Milliseconds 500 };' +
    'Get-Mine | ForEach-Object { Stop-Process -Id $_.ProcessId -Force;' +
    ' $killed = $killed + 1 };' +
    'Start-Sleep -Milliseconds 500;' +
    'Get-Mine | ForEach-Object { Stop-Process -Id $_.ProcessId -Force;' +
    ' $killed = $killed + 1 };' +
    'Start-Sleep -Milliseconds 300;' +
    '$left = (Get-Mine).Count;' +
    'if ($killed -gt 200) { $killed = 200 }; if ($left -gt 200) { $left = 200 };' +
    'exit ($killed * 1000 + $left)';
  if not Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
              '-NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "' + psCmd + '"',
              '', SW_HIDE, ewWaitUntilTerminated, resultCode) then
  begin
    Log('muezzin: ' + why + ': the process check could not be run at all');
    Result := -1;
    Exit;
  end;
  if resultCode < 0 then
  begin
    // A negative exit code is not one this script can produce, so it is taken
    // for a check that never got as far as answering, not for a clean run.
    Log('muezzin: ' + why + ': the process check answered with exit ' +
        IntToStr(resultCode));
    Result := -1;
    Exit;
  end;
  endedCount := resultCode div 1000;
  stillThere := resultCode mod 1000;
  if (endedCount = 0) and (stillThere = 0) then
    Log('muezzin: ' + why + ': nothing named muezzin was holding ' + appDir)
  else if stillThere = 0 then
    Log('muezzin: ' + why + ': ended ' + IntToStr(endedCount) +
        ' process(es) named muezzin that were holding ' + appDir)
  else
    Log('muezzin: ' + why + ': ' + IntToStr(stillThere) +
        ' process(es) named muezzin survived being waited for and ended, so the files in ' +
        appDir + ' may not be replaceable; ' + IntToStr(endedCount) + ' were ended first');
  Result := stillThere;
end;

function ClearWrapperLogs(const why: String): Integer;
var
  attempt, i, j, tries, total, survived: Integer;
  appDir, path: String;
  names, left, keep: TArrayOfString;
begin
  // Delete the log files the service writes beside itself, so the program folder
  // can leave with the program.
  //
  // Measured on the machine this shipped to, 13:19 on 2026-11-24, from that
  // machine's own wrapper log: the uninstaller asked the service to stop, the
  // wrapper wrote "Service 'muezzin (adhan daemon) (muezzin)' stopped
  // successfully" and then "was uninstalled successfully", and both exes did get
  // deleted. The folder survived, holding muezzin-service.out.log,
  // muezzin-service.err.log and muezzin-service.wrapper.log. Those are not the
  // household's logs - those live in {commonappdata} and nothing here touches
  // them - they are the console output WinSW keeps next to the service, and the
  // wrapper had them open when Inno reached the folder, so the folder could not
  // be removed. Row C11 of the UAT checklist asks whether the folder is gone, and
  // a folder holding three files is not gone in any way that matters to the
  // person checking it.
  //
  // What gets waited for is the file, not the process. SweepOwnProcesses has
  // already spent about six seconds on the process by the time this runs, and a
  // process that answered a stop politely can still leave a handle behind. Nine
  // tries 750 ms apart spends about the same patience again on the files. A name
  // that has gone missing between the listing and the attempt is not counted as a
  // survivor: DeleteFile answers no to that as well, and only FileExists decides.
  //
  // The names are written out rather than searched for, because a search is not
  // available. Inno 6.7.3 does have FindFirst and TFindRec in [Code], but it has
  // none of the file-attribute constants its own documentation lists: faAnyAll,
  // faArchive, faDirectory, faFile, faAny, faNormal, faHidden and faReadOnly all
  // fail to compile with "Unknown identifier", measured here by compiling one
  // file per name. So the list is bounded by the service definition's own roll
  // policy - it keeps five rolled logs per stream, three streams, eighteen names.
  //
  // The other half of the coverage is the [UninstallDelete] line below, which
  // names the same files with a wildcard and is not a duplicate of this list but
  // the net under it: if WinSW numbers its rolled files the other way round, as
  // .err.log.1 instead of .err.1.log, this list misses them and that line gets
  // them. What this function adds over that line is the waiting.
  //
  // This runs on uninstall only. An upgrade keeps the logs, because the log of
  // the build that just failed is the one thing a person wants while the next one
  // is being installed.
  appDir := RemoveBackslashUnlessRoot(ExpandConstant('{app}'));
  tries := 9;
  SetArrayLength(names, 18);
  names[0] := 'muezzin-service.wrapper.log';
  names[1] := 'muezzin-service.wrapper.1.log';
  names[2] := 'muezzin-service.wrapper.2.log';
  names[3] := 'muezzin-service.wrapper.3.log';
  names[4] := 'muezzin-service.wrapper.4.log';
  names[5] := 'muezzin-service.wrapper.5.log';
  names[6] := 'muezzin-service.err.log';
  names[7] := 'muezzin-service.err.1.log';
  names[8] := 'muezzin-service.err.2.log';
  names[9] := 'muezzin-service.err.3.log';
  names[10] := 'muezzin-service.err.4.log';
  names[11] := 'muezzin-service.err.5.log';
  names[12] := 'muezzin-service.out.log';
  names[13] := 'muezzin-service.out.1.log';
  names[14] := 'muezzin-service.out.2.log';
  names[15] := 'muezzin-service.out.3.log';
  names[16] := 'muezzin-service.out.4.log';
  names[17] := 'muezzin-service.out.5.log';
  SetArrayLength(left, 0);
  for i := 0 to GetArrayLength(names) - 1 do
    if FileExists(appDir + '\' + names[i]) then
    begin
      SetArrayLength(left, GetArrayLength(left) + 1);
      left[GetArrayLength(left) - 1] := names[i];
    end;
  total := GetArrayLength(left);
  for attempt := 1 to tries do
  begin
    SetArrayLength(keep, GetArrayLength(left));
    j := 0;
    for i := 0 to GetArrayLength(left) - 1 do
    begin
      path := appDir + '\' + left[i];
      if DeleteFile(path) then
        Continue;
      if FileExists(path) then
      begin
        keep[j] := left[i];
        j := j + 1;
      end;
    end;
    SetArrayLength(left, j);
    for i := 0 to j - 1 do
      left[i] := keep[i];
    if j = 0 then
      Break;
    if attempt < tries then
      Sleep(750);
  end;
  survived := GetArrayLength(left);
  if total = 0 then
    Log('muezzin: ' + why + ': no log files of the service were left in ' + appDir)
  else if survived = 0 then
    Log('muezzin: ' + why + ': deleted ' + IntToStr(total) + ' log file(s) the service had' +
        ' been writing in ' + appDir + ', needing ' + IntToStr(attempt - 1) + ' wait(s) of 750 ms')
  else
    Log('muezzin: ' + why + ': ' + IntToStr(survived) + ' of ' + IntToStr(total) +
        ' log file(s) in ' + appDir + ' would not delete in ' + IntToStr(tries) +
        ' tries, so that folder will still be there afterwards');
  Result := survived;
end;
function XmlEscape(const value: String): String;
begin
  // An account name or password is going between XML tags, and & is the one
  // that bites silently: it turns the rest of the line into an entity. & has
  // to go first or the new ampersands get escaped again.
  Result := value;
  StringChange(Result, '&', '&amp;');
  StringChange(Result, '<', '&lt;');
  StringChange(Result, '>', '&gt;');
end;

function ServiceAccountBlock(const user, password: String): String;
begin
  // WinSW 2.12's own spelling, from the config docs for the version build.ps1
  // pins: <serviceaccount> with <user> and <password>, <domain> optional
  // because a name of the form PC\muezzin carries it, and
  // <allowservicelogon>true</allowservicelogon> so the account is granted the
  // right registration fails without. LocalSystem has no password and WinSW
  // ignores one it is given, so writing the tag only when a password was
  // typed is tidier than arguing about it.
  // No leading indent on purpose: PutServiceAccount adds the two spaces, the
  // same as it does for a block carried over from a previous install, whose
  // own indentation is not part of what Pos finds.
  Result := '<serviceaccount>' + #13#10 +
            '    <user>' + XmlEscape(user) + '</user>' + #13#10;
  if password <> '' then
    Result := Result + '    <password>' + XmlEscape(password) + '</password>' + #13#10;
  Result := Result + '    <allowservicelogon>true</allowservicelogon>' + #13#10 +
            '  </serviceaccount>' + #13#10;
end;

procedure CarryAccountBlock();
var
  xmlText: AnsiString;
  startAt, endAt: Integer;
begin
  // Read the definition that is on disk *now*, before [Files] replaces it with
  // the pristine one the installer ships: ssPreInstall is the only moment both
  // exist to be told apart. Whatever an earlier install wrote goes back
  // verbatim - no parsing, no re-escaping, because it was already working.
  CarriedAccount := '';
  if not LoadStringFromFile(ServiceDefinition(), xmlText) then Exit;
  startAt := Pos('<serviceaccount>', xmlText);
  if startAt = 0 then Exit;
  endAt := Pos('</serviceaccount>', xmlText);
  if endAt <= startAt then Exit;
  endAt := endAt + Length('</serviceaccount>') - 1;
  CarriedAccount := Copy(xmlText, startAt, endAt - startAt + 1);
  Log('muezzin: the service in this folder runs as a named account; carrying it over');
end;

procedure PutServiceAccount(const block: AnsiString);
var
  xmlPath: String;
  xmlText, pre, post: AnsiString;
  at: Integer;
  inserted: AnsiString;
begin
  // The only way to set an account in WinSW 2.12 is the config file: its own
  // help lists install, uninstall, start, stop, stopwait, restart, restart!,
  // status, test, testwait, version and help, and there is no command among
  // them that changes the log-on. So the file is written here, in
  // ssPostInstall, which runs after the copy and before this same step
  // registers and starts the service - that ordering is the whole design, and
  // it is also why {app} is safe to expand on this line and not in
  // InitializeWizard.
  xmlPath := ServiceDefinition();
  if not LoadStringFromFile(xmlPath, xmlText) then
  begin
    Log('muezzin: no service definition at ' + xmlPath + '; the account was not set');
    Exit;
  end;
  at := Pos('</service>', xmlText);
  if at = 0 then
  begin
    Log('muezzin: no </service> line in ' + xmlPath + '; the account was not set');
    Exit;
  end;
  // The file's own text is kept in AnsiString the whole way through: the
  // comments in it are UTF-8 and there is no reason to hand them to a
  // codepage conversion on the way to a file that is being rewritten. Only the
  // block being added is converted, and that is ASCII by construction.
  pre := Copy(xmlText, 1, at - 1);
  post := Copy(xmlText, at, Length(xmlText) - at + 1);
  inserted := '  ' + block + #13#10;
  if SaveStringToFile(xmlPath, pre + inserted + post, False) then
    Log('muezzin: the service definition now names the account to run as')
  else
    Log('muezzin: could not write the account into ' + xmlPath);
end;

procedure FindSources();
var
  candidates: TArrayOfString;
  i: Integer;
  parent: String;
begin
  ConfigFrom := '';
  MediaFrom := '';
  if FileExists(ExpandConstant('{commonappdata}\muezzin\muezzin.yaml')) then
    Exit;   // this machine already has a household profile: nothing to migrate

  SetArrayLength(candidates, 3);
  candidates[0] := ExpandConstant('{src}\muezzin.yaml');
  candidates[1] := ExpandConstant('{userdocs}\azan-speaker-app\muezzin.yaml');
  candidates[2] := ExpandConstant('{userdocs}\muezzin\muezzin.yaml');
  for i := 0 to GetArrayLength(candidates) - 1 do
    if FileExists(candidates[i]) then
    begin
      ConfigFrom := candidates[i];
      Break;
    end;
  if ConfigFrom <> '' then
  begin
    // The media folder beside that profile: the checkout's own, which is
    // where a tester's recordings already are.
    parent := ConfigFrom;
    Delete(parent, Length(parent) - Length('muezzin.yaml') + 1, Length('muezzin.yaml'));
    MediaFrom := parent + 'media';
    if not DirExists(MediaFrom) then MediaFrom := '';
  end;
end;

function TasksPageVisible(): Boolean;
begin
  Result := (ConfigFrom <> '') or (MediaFrom <> '');
end;

procedure BuildMigrationPage();
begin
  // An options page, not a query page: what is being asked for is two ticks,
  // and TInputQueryWizardPage only knows edit boxes (measured when
  // TValues turned out to be no such thing). The page exists in every wizard
  // - Inno creates custom pages in InitializeWizard and nowhere else - and
  // ShouldSkipPage below is what hides it when there is nothing to migrate.
  // The ticks start down: bringing somebody's timetable in is their
  // decision, not the installer's.
  MigrationPage := CreateInputOptionPage(wpSelectDir,
    'Your existing setup', 'Bring the previous copy''s files along?',
    'muezzin will leave these where they are unless you tick them. Nothing is ' +
    'ever overwritten: a file already in the destination folder is kept.',
    False, False);
  if ConfigFrom <> '' then
    MigrationPage.Add('Move the profile (' + ConfigFrom + ') to %commonappdata%\muezzin');
  if MediaFrom <> '' then
    MigrationPage.Add('Copy the recordings (' + MediaFrom + ') where the service will look for them');
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  // The migration page earns its place by having something to migrate.
  Result := (MigrationPage <> nil) and (PageID = MigrationPage.ID) and not TasksPageVisible();
end;

procedure InitializeWizard();
var
  page: TInputQueryWizardPage;
  subCaption: String;
begin
  // Built-in wizard pages have predefined identifiers - wpWelcome,
  // wpSelectDir - and the custom pages hang off them. (The first version of
  // this file guessed at names like WelcomePageID, and also at
  // WizardInfoAppendPage, which is not a function at all: in 6.7 the compiler
  // was the only honest witness to either mistake.)
  FindSources();
  if ConfigFrom <> '' then
    CreateOutputMsgPage(wpWelcome, 'A previous copy of muezzin',
      'Your schedule and your recordings stay where they are',
      'A muezzin profile from a previous copy was found at:' + #13#10 +
      ConfigFrom + #13#10 + #13#10 +
      'The next steps let you move it, and its recordings, where the service ' +
      'will look for them. Nothing is overwritten.');

  // The order the questions are asked in: the folder, then the files you
  // already have, then the account the service will run as. Creating both
  // pages "after the folder page" puts the one created last first, so the
  // account page is built before the migration page on purpose.

  // Which account the service runs as, for the people whose Cast discovery
  // needs one. The default - leave both fields empty - is LocalSystem, the
  // Windows default, and it is the first thing to measure against UAT row
  // C7: a service is not a logged-in user, and whether LocalSystem's
  // interfaces and firewall profile reach the LAN is a fact to be observed
  // on the machine, not a claim this installer makes. An upgrade carries the
  // previous account over on its own (CarryAccountBlock), which is what makes
  // the sentence below about leaving the fields empty true; it is not decided
  // here, because nothing in this procedure may ask where the program went.
  subCaption := 'Leave both fields empty to use the Windows default (LocalSystem), ' +
    'or to keep the account a muezzin service already on this machine runs as. ' +
    'Only fill them in if that account cannot see your speakers on the LAN: the ' +
    'account needs no administrator rights, and its password is stored in the ' +
    'service definition under Program Files, which every local user can read.';
  page := CreateInputQueryPage(wpSelectDir,
    'Service account', 'Run the muezzin service as a specific Windows user',
    subCaption);
  page.Add('User name (for example DESKTOP-ABC\muezzin):', False);
  page.Add('Password:', True);
  // Read in CurStepChanged, after the wizard is over, so a cancelled wizard
  // never touches a running service.
  LogonPage := page;

  BuildMigrationPage();
end;

procedure MigrateConfig();
var
  dest: String;
begin
  if (MigrationPage = nil) or (ConfigFrom = '') then Exit;
  if not MigrationPage.Values[0] then Exit;
  dest := ExpandConstant('{commonappdata}\muezzin\muezzin.yaml');
  if FileExists(dest) then
  begin
    // The rule the container's entrypoint keeps, in an installer's clothes:
    // a profile here is either absent or yours, never half-written over.
    Log('muezzin: keeping the existing profile at ' + dest);
    Exit;
  end;
  CopyFile(ConfigSource(), dest, True);
  Log('muezzin: migrated the profile from ' + ConfigSource());
end;

function MediaDirOf(const text: String; var value: String): Boolean;
var
  key: String;
  remainder: String;
  consumed, keyAt, lineStart, p, valueStart, valueEnd: Integer;
  c: Char;
begin
  // The one setting this installer reads, read the way the program itself
  // reads its profile: by the key's name, one line at a time, with no YAML
  // parser. Inno's [Code] has no regexp this file can trust from memory - the
  // NoError variant of its regexp helper does not exist in 6.7 - and a
  // scanner that compiles beats a pattern that guesses.
  Result := False;
  value := '';
  key := 'media_dir:';
  remainder := text;
  consumed := 0;
  while True do
  begin
    keyAt := Pos(key, remainder);
    if keyAt = 0 then Exit;
    keyAt := consumed + keyAt;

    // The key has to begin its own line, allowing only indentation before it.
    // A profile that mentions the word inside a comment is not a setting - and
    // an earlier comment must not end the search, because the real setting may
    // be the next mention of the word.
    lineStart := keyAt;
    while (lineStart > 1) and (text[lineStart - 1] <> #10) do
      lineStart := lineStart - 1;
    p := lineStart;
    while (p < keyAt) and ((text[p] = ' ') or (text[p] = #9)) do
      p := p + 1;
    if p = keyAt then
    begin
      // The value: past the colon, to the end of the line, then cut back to
      // what YAML would hand back - a trailing " # note" is a note, and a
      // value in quotes is a value with the quotes taken off. This is a
      // destination the installer is going to write into, so a path with a
      // sentence glued to the end of it is not acceptable.
      p := keyAt + Length(key);
      while (p <= Length(text)) and ((text[p] = ' ') or (text[p] = #9)) do
        p := p + 1;
      valueStart := p;
      valueEnd := valueStart - 1;
      while valueEnd + 1 <= Length(text) do
      begin
        c := text[valueEnd + 1];
        if (c = #10) or (c = #13) then Break;
        valueEnd := valueEnd + 1;
      end;
      while (valueEnd >= valueStart) and ((text[valueEnd] = ' ') or (text[valueEnd] = #9)) do
        valueEnd := valueEnd - 1;
      if (valueEnd >= valueStart + 1) and ((text[valueStart] = '"') or (text[valueStart] = #39)) and
         (text[valueEnd] = text[valueStart]) then
      begin
        valueStart := valueStart + 1;
        valueEnd := valueEnd - 1;
      end
      else
      begin
        p := valueStart + 1;
        while p <= valueEnd do
        begin
          if (text[p] = '#') and (text[p - 1] = ' ') then Break;
          p := p + 1;
        end;
        if p <= valueEnd then
          valueEnd := p - 2;  // -2: the space before the hash goes too
      end;
      while (valueEnd >= valueStart) and ((text[valueEnd] = ' ') or (text[valueEnd] = #9)) do
        valueEnd := valueEnd - 1;
      if valueEnd >= valueStart then
      begin
        value := Copy(text, valueStart, valueEnd - valueStart + 1);
        Result := True;
        Exit;
      end;
    end;

    // Not this mention of the word: keep looking after it.
    consumed := keyAt + Length(key) - 1;
    remainder := Copy(text, consumed + 1, Length(text) - consumed);
  end;
end;

procedure CopyOneExtension(const fromDir, toDir, pattern: String; var copied: Integer);
var
  search: TFindRec;
  fileName: String;
begin
  // One extension per FindFirst call, because this 6.7 gives FindFirst no
  // attribute parameter and TFindRec no attribute field - probed here, three
  // spellings of the call and four candidate fields, and the honest answer is
  // FindFirst(path, rec) with a record that carries a name and a size and
  // nothing about what kind of thing it is. So the pattern has to do all the
  // selecting, and a folder named something.mp3 would be copied as if it were
  // audio: CopyFile refuses it quietly, and the count below is what the log
  // reports, so an almost-copy is at least an honest one.
  if not FindFirst(fromDir + '\' + pattern, search) then Exit;
  try
    fileName := toDir + '\' + search.Name;
    if not FileExists(fileName) then
    begin
      // CopyFile's third word is FailIfNewExists - the opposite sense of the
      // older FileCopy's third word, which meant overwrite. True is the
      // promise this installer makes either way.
      if CopyFile(fromDir + '\' + search.Name, fileName, True) then
        copied := copied + 1;
    end;
    while FindNext(search) do
    begin
      fileName := toDir + '\' + search.Name;
      if not FileExists(fileName) then
        if CopyFile(fromDir + '\' + search.Name, fileName, True) then
          copied := copied + 1;
    end;
  finally
    FindClose(search);
  end;
end;

procedure MigrateMedia();
var
  destDir, mediaLine, profileStr: String;
  profileText: AnsiString;
  copied: Integer;
begin
  if (MigrationPage = nil) or (MediaFrom = '') then Exit;
  // Index 1 is the recordings box: FindSources only ever finds media beside
  // a profile it found, so when this box exists the profile box is index 0.
  if not MigrationPage.Values[1] then Exit;

  // Where the migrated profile actually looks for audio. A starter profile
  // names media_dir relative to itself, so beside the copied profile is
  // usually right - but a profile that names an absolute folder, which the
  // container's starter does, is followed to that folder instead of being
  // argued with. And the profile itself is never edited to agree.
  destDir := ExpandConstant('{commonappdata}\muezzin\media');
  if FileExists(ConfigSource()) then
  begin
    if LoadStringFromFile(ConfigSource(), profileText) then
    begin
      // LoadStringFromFile hands back AnsiString text; the scanner wants a
      // String, and the conversion is the whole of this extra step.
      profileStr := profileText;
      if MediaDirOf(profileStr, mediaLine) then
      begin
        // A drive letter and a backslash is how an absolute Windows folder
        // announces itself; a relative name like "media" belongs beside the
        // profile, which is where destDir already points.
        if (Pos(':', mediaLine) > 1) and (Pos('\', mediaLine) > 0) then
          destDir := mediaLine;
      end;
    end;
  end;
  ForceDirectories(destDir);

  // The names muezzin's own library uses are the pattern: audio in the
  // profile's media folder is flat, not nested, so an extension-by-extension
  // pass at one level is the whole of the copy. An existing file is kept.
  copied := 0;
  CopyOneExtension(MediaFrom, destDir, '*.mp3', copied);
  CopyOneExtension(MediaFrom, destDir, '*.wav', copied);
  CopyOneExtension(MediaFrom, destDir, '*.m4a', copied);
  Log('muezzin: copied ' + IntToStr(copied) + ' recording(s) from ' + MediaFrom +
      ' to ' + destDir);
end;

procedure TakeDownPreviousInstall(const why: String);
var
  resultCode: Integer;
begin
  // An upgrade replaces files that a running service is holding open, and the
  // wrapper refuses to register a service name that is already registered. So
  // the old one goes down, and off, before a single byte moves. Doing this
  // before the copy is the whole point: by the time a post-copy step runs, the
  // copy has already failed on a locked exe, which is the failure that was
  // reported against the first builds of this installer.
  //
  // The old definition is read here, and nowhere else: this is the one
  // moment the file a previous setup wrote still exists, before [Files]
  // replaces it with the pristine one this installer ships. An upgrade that
  // quietly fell back to LocalSystem would be an upgrade that changed which
  // speakers answered, so whatever is in there travels.
  CarryAccountBlock();
  if FileExists(ServiceExe()) then
  begin
    // The exit codes go to the log because a failed stop shows up later as a
    // file lock with nothing to explain it.
    Exec(ServiceExe(), 'stop', '', SW_HIDE, ewWaitUntilTerminated, resultCode);
    Log('muezzin: asked the existing service to stop (wrapper exit ' + IntToStr(resultCode) + ')');
    Exec(ServiceExe(), 'uninstall', '', SW_HIDE, ewWaitUntilTerminated, resultCode);
    Log('muezzin: unregistered the existing service (wrapper exit ' + IntToStr(resultCode) + ')');
  end;
  // Outside the guard above, and after both calls: an earlier uninstall that
  // left a process behind leaves the wrapper on disk but nothing to ask it
  // politely, and the process - not the service - is what stands between this
  // step and the copy that follows it.
  SweepOwnProcesses(why);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  // Not from CurStepChanged. Inno Setup 6.7.3 accepts ssPreInstall as an
  // identifier and never sends it: a probe build logging every CurStepChanged
  // call on this machine printed ordinals 1, 2 and 3, none of them equal to
  // ssPreInstall, and the shipped help lists only ssInstall, ssPostInstall and
  // ssDone as the steps that fire. The version of this file that hung the
  // teardown on ssPreInstall therefore never took anything down, which is how
  // an upgrade reached the copy with the previous service still running.
  // PrepareToInstall does run, and it runs before Setup decides which of its
  // own files are in use, so it is the earliest moment the lock can be
  // released by choice rather than met as an error.
  TakeDownPreviousInstall('upgrade');
  NeedsRestart := False;
  Result := '';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  resultCode: Integer;
  user, password, profilePath: String;
begin
  // What has to happen before the files move lives in PrepareToInstall, above.
  if CurStep <> ssPostInstall then Exit;

  // Migration first: the service is registered and started at the end of this
  // same step, and it should meet the household's folders before it meets the
  // timetable.
  MigrateConfig();
  MigrateMedia();

  // Then a household that is starting from nothing gets its profile. This is
  // not decoration: the panel writes a location into an existing YAML and says
  // "run muezzin init" when there is none, and a daemon pointed at a profile
  // that is not there exits at once - which under a service is a restart loop
  // and a browser aimed at a port nobody answers on. Same first act as the
  // container's entrypoint, before the service is registered. init exits 1
  // rather than rewriting a profile that already exists, which is the promise
  // this installer makes everywhere else, so it is called unconditionally.
  profilePath := ExpandConstant('{commonappdata}\muezzin\muezzin.yaml');
  if not Exec(ExpandConstant('{app}\muezzin.exe'), 'init -c "' + profilePath + '"',
              '', SW_HIDE, ewWaitUntilTerminated, resultCode) then
    Log('muezzin: could not run muezzin init for a first profile')
  else if resultCode = 0 then
    Log('muezzin: wrote a starter profile at ' + profilePath +
        ' - the page finishes it, and no later install rewrites it')
  else
    Log('muezzin: a profile is already there; init left it alone');

  // The account, last of the three writes: what was typed wins; otherwise what
  // the previous install had, carried over; otherwise the shipped definition,
  // which names no account and so runs as the Windows default.
  //
  // This used to be `muezzin-service.exe user <name> <password>`, which is not
  // a command: the 2.12 wrapper's own help was run here and lists install,
  // uninstall, start, stop, stopwait, restart, restart!, status, test,
  // testwait, version and help. The call would have "succeeded" as a process,
  // done nothing, and left the wizard lying about the account it set. The
  // config file is the only way this version takes an account, so the file is
  // written here - before the same step registers the service, which is the
  // only order in which that write can matter. Registration used to be a [Run]
  // entry, and [Run] entries were measured on an installed machine running
  // before this step, which means a named account would have reached the file
  // only after the service had already been registered and started with the
  // stock one. See the register/start block below for the measured timeline.
  user := '';
  password := '';
  if LogonPage <> nil then
  begin
    user := LogonPage.Values[0];
    password := LogonPage.Values[1];
  end;
  if user <> '' then
  begin
    PutServiceAccount(ServiceAccountBlock(user, password));
    Log('muezzin: the service will run as ' + user);
  end
  else if CarriedAccount <> '' then
    Log('muezzin: the service keeps the account the previous install chose')
  else
    Log('muezzin: the service will run as the Windows default (LocalSystem)');

  // Register and start here rather than in [Run], because [Run] entries run
  // before this step, and the order is what a person feels. The first build
  // measured on a real machine: the service was started at 17:02:21.9, about a
  // second before the profile was written a few lines above, so the daemon
  // exited 2 on a missing profile and the service's own ten-second restart
  // delay covered the mistake - the wrapper log shows the second attempt
  // starting at 17:02:33.3 and the page answering at 17:02:34.1. Eleven of
  // those seconds were the delay. Here the profile exists and the account is
  // already in the definition, so the first start is the only start.
  if not Exec(ServiceExe(), 'install', '', SW_HIDE, ewWaitUntilTerminated, resultCode) then
    Log('muezzin: could not run muezzin-service.exe install')
  else if resultCode <> 0 then
    Log('muezzin: muezzin-service.exe install exited ' + IntToStr(resultCode));

  if not Exec(ServiceExe(), 'start', '', SW_HIDE, ewWaitUntilTerminated, resultCode) then
    Log('muezzin: could not run muezzin-service.exe start')
  else if resultCode <> 0 then
    // Nothing here pretends to know what a service failure means: the pointer
    // is to the two places that do.
    Log('muezzin: muezzin-service.exe start exited ' + IntToStr(resultCode) +
        '; if the page does not answer, read ' +
        ExpandConstant('{app}\muezzin-service.wrapper.log') +
        ' and run muezzin-service.exe status');
end;

// The uninstall closes with a few words for the person who ran it, and those
// words are the reason this helper exists. Measured on 2026-11-24 while this
// very routine was being probed: a message box that [Code] opens during a
// silent uninstall is never answered, because nobody is looking at it, so the
// uninstaller never exits. It sits on its uninstall data, on its log file and
// on the app-ID mutex, and every later uninstall of the same app then refuses
// and quits with nothing done - which is how four probe runs in a row lost all
// of their cases while the files they were supposed to delete stayed put.
// WizardSilent answers true for /SILENT and for /VERYSILENT alike; a probe
// built today is the only way to know a thing like that about Inno. So the
// words go to the log, which costs nothing and helps later when a folder has
// to be chased down, and reach the screen only when there is a window for
// them. All four notes say the same kind of thing, so they share one helper
// and one icon; the scarier icon on the first was only ever a choice.
procedure ExplainUninstall(const msg: String);
begin
  Log('muezzin: ' + msg);
  if not WizardSilent then
    MsgBox(msg, mbInformation, MB_OK);
end;

// The folder can outlive the uninstall for a reason that is nobody's fault,
// and "muezzin is removed" would then be true but not enough: a person
// double-clicking an uninstaller is entitled to know that a folder is still
// standing and what is in it. This is the reading of that folder.
//
// Measured on 2026-11-25 against a probe install holding one installed file,
// two files of mine and a folder of mine: FindFirst here takes two arguments,
// a name and a record - a third (the attributes filter the documentation of my
// memory promises) is "Variable Expected" at compile time, which is also why
// this [Code] has no faFile or faAnyAll to pass: the parameter it would go in
// does not exist. So the folder is read unfiltered, and a directory is
// spotted by bit 16 of rec.Attributes, which is the value Windows marks one
// with. The probe named all three of the things that survived, said which one
// was the folder, gave the byte counts for the files, and listed no '.' or
// '..'; the two checks below stay anyway, because they cost nothing and the
// answer comes from a Windows API rather than from Inno. Only the first three
// names reach the message: a folder full of somebody's photographs is not
// something to print out in full, so the count travels with the sample.
function DescribeLeftovers(const dir: String; var names: String): Integer;
var
  found: Integer;
  rec: TFindRec;
begin
  Result := 0;
  names := '';
  found := 0;
  if FindFirst(dir + '\*', rec) then
  begin
    try
      repeat
        if (rec.Name <> '.') and (rec.Name <> '..') then
        begin
          found := found + 1;
          if found <= 3 then
          begin
            if names <> '' then
              names := names + ', ';
            if (rec.Attributes and 16) <> 0 then
              names := names + rec.Name + ' (a folder)'
            else
              names := names + rec.Name;
          end;
        end;
      until not FindNext(rec);
    finally
      FindClose(rec);
    end;
  end;
  Result := found;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  resultCode: Integer;
  appDir, leftNames, moreNames: String;
  leftCount: Integer;
begin
  if CurUninstallStep = usUninstall then
  begin
    // The wrapper first, while it still exists on disk: stop, then unregister.
    Exec(ServiceExe(), 'stop', '', SW_HIDE, ewWaitUntilTerminated, resultCode);
    Exec(ServiceExe(), 'uninstall', '', SW_HIDE, ewWaitUntilTerminated, resultCode);
    // Then the process itself, which is the last thing holding the program
    // files: this step is the moment Inno goes on to delete those files, and a
    // "stopped successfully" from the wrapper does not mean the process is
    // gone. The count is kept so the closing message can be honest about it.
    UninstallHeld := SweepOwnProcesses('uninstall');
    // The service's own logs are then the last files in the folder, and while
    // they are there the folder outlives the program: see ClearWrapperLogs.
    UninstallLogsLeft := ClearWrapperLogs('uninstall');
    // The two rules the installer opened, by the names it opened them under.
    Exec('netsh', 'advfirewall firewall delete rule name="muezzin panel"', '', SW_HIDE, ewWaitUntilTerminated, resultCode);
    Exec('netsh', 'advfirewall firewall delete rule name="muezzin media"', '', SW_HIDE, ewWaitUntilTerminated, resultCode);
  end;
  if CurUninstallStep = usDone then
  begin
    if UninstallHeld > 0 then
      // Said out loud rather than left as a folder full of files nobody
      // remembers installing: the process was still there when this finished,
      // so some of the program probably is too.
      ExplainUninstall('muezzin is removed, but ' + IntToStr(UninstallHeld) +
                       ' muezzin process(es) were still running when this finished, so the program' +
                       ' files in ' + ExpandConstant('{app}') + ' may still be there. A restart,' +
                       ' then deleting that folder, finishes the job. Your profile, recordings and' +
                       ' logs are in ' + ExpandConstant('{commonappdata}\muezzin') +
                       ' either way, and deleting them is yours to decide.')
    else if UninstallLogsLeft > 0 then
      ExplainUninstall('muezzin is removed, but ' + IntToStr(UninstallLogsLeft) +
                       ' log file(s) the service was still writing could not be deleted, so ' +
                       ExpandConstant('{app}') + ' is still there. Nothing in it runs, and deleting' +
                       ' the folder finishes the job. Your profile, recordings and logs are in ' +
                       ExpandConstant('{commonappdata}\muezzin') + ' either way, and deleting them is' +
                       ' yours to decide.')
    else if DirExists(RemoveBackslashUnlessRoot(ExpandConstant('{app}'))) then
    begin
      // Neither of the two above fired, so the program's own files went and
      // the service's logs went, and the folder still stands: the dirifempty
      // line in [UninstallDelete] leaves a folder alone when something is in
      // it, and Inno's own log records that as "Failed to delete directory
      // (145)" - 145 is the directory-not-empty error, measured today. The old
      // closing note was simply the plain one, which was true and said nothing
      // about the folder, so the honest version names what is in the way
      // instead of describing it: "delete that folder" is advice a person can
      // only follow after they have looked.
      appDir := RemoveBackslashUnlessRoot(ExpandConstant('{app}'));
      leftCount := DescribeLeftovers(appDir, leftNames);
      if leftCount = 0 then
        // Either the folder is empty and would not delete, or it could not be
        // read at all. Not claimed either way.
        ExplainUninstall('muezzin is removed, but ' + appDir + ' is still there, and it could not be' +
                         ' listed or deleted while this ran. Nothing in it is needed to run muezzin; a' +
                         ' restart and deleting it finishes the job. Your profile, recordings and logs' +
                         ' are in ' + ExpandConstant('{commonappdata}\muezzin') + ' either way, and' +
                         ' deleting them is yours to decide.')
      else
      begin
        moreNames := '';
        if leftCount > 3 then
          moreNames := ' and ' + IntToStr(leftCount - 3) + ' more';
        ExplainUninstall('muezzin is removed, but ' + appDir + ' is still there because it is not' +
                         ' empty: ' + leftNames + moreNames + '. None of that is muezzin, and none of it' +
                         ' is your profile, which is in ' + ExpandConstant('{commonappdata}\muezzin') +
                         '. Look inside, and delete the folder once you are sure nothing in it is' +
                         ' yours.');
      end;
    end
    else
      ExplainUninstall('muezzin is removed. Your profile, recordings and logs are still in ' +
                       ExpandConstant('{commonappdata}\muezzin') + ' - deleting them is yours to decide.');
  end;
end;

[UninstallDelete]
; The service's console logs, which it writes beside its own exe rather than in
; the household's folder. ClearWrapperLogs above waits for these files and
; reports what would not go; this is the same list written where Inno can see it,
; and it is the net under that list rather than a copy of it: the roll policy in
; muezzin-service.xml may number a rolled file .err.1.log or .err.log.1, and the
; two stars catch either. Then the folder, but only if nothing is left in it, so
; that a file somebody else put there keeps the folder the way it should - and
; CurUninstallStepChanged closes with the names of whatever it was that kept it,
; so the folder is never left standing without an explanation. Once
; the logs are gone Inno would take the folder anyway - writing the line down is
; what turns row C11 of the UAT checklist into something the file can be read
; against.
Type: files; Name: "{app}\muezzin-service*.log*"
Type: dirifempty; Name: "{app}"
[Run]
; The firewall, by exe path rather than port range: the rule travels with the
; one program that listens. The boundary is the local subnet rather than the
; Private profile, because a home network is routinely filed as Public by
; Windows — measured on the first machine this shipped to, both adapters were
; Public — and a Private-only rule there strands every speaker quietly: the
; scan finds them, the page adds one, the daemon hands it a URL and the
; speaker cannot fetch it. remoteip=localsubnet keeps both ports closed to
; anything that is not on a network this machine is itself attached to. The
; delete comes first, because `add rule` does not replace: an upgrade that
; only added would leave last version's rule standing next to this one.
Filename: "netsh"; Parameters: "advfirewall firewall delete rule name=""muezzin panel"""; Flags: runhidden
Filename: "netsh"; Parameters: "advfirewall firewall add rule name=""muezzin panel"" dir=in action=allow program=""{app}\muezzin.exe"" enable=yes profile=any remoteip=localsubnet"; Flags: runhidden
Filename: "netsh"; Parameters: "advfirewall firewall delete rule name=""muezzin media"""; Flags: runhidden
Filename: "netsh"; Parameters: "advfirewall firewall add rule name=""muezzin media"" dir=in action=allow program=""{app}\muezzin.exe"" enable=yes profile=any remoteip=localsubnet"; Flags: runhidden
; The service is registered and started in [Code], at ssPostInstall, not here:
; [Run] entries were measured running before that step, which started the
; daemon before the profile it is pointed at existed. See CurStepChanged.
; The page: the same first act as the container's entrypoint - a browser to
; finish setup in, not a log to read.
Filename: "http://127.0.0.1:8020/"; Description: "Open the muezzin page"; Flags: postinstall shellexec skipifsilent nowait
