; ════════════════════════════════════════════════════════════════════════
; Krexion — Inno Setup Installer Script (White-Label Edition)
; ════════════════════════════════════════════════════════════════════════
;
; Build with:
;     "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\krexion-setup.iss
;
; Produces:  installer\Output\Krexion-Setup-<version>.exe
;
; What it installs (all in C:\Program Files\Krexion by default):
;   • bin\krexion-core.exe            — Krexion-branded core engine binary
;   • bin\krexion-service.exe         — Windows service wrapper (renamed NSSM)
;   • database\                       — Embedded local database engine
;   • browser-engine\                 — Bundled Chromium + WebKit (Android/iOS)
;   • krexion-kernel\                 — Cloak C++ Chromium (AdsPower-class headed profiles)
;   • frontend\                       — Production React build
;   • krexion-tray.exe                — System tray app (optional)
;
; What it registers:
;   • Windows Service "KrexionBackend"   (auto-start)
;   • Windows Service "KrexionDatabase"  (auto-start)
;   • Start Menu shortcut "Krexion"
;   • Desktop shortcut "Krexion" (optional)
;   • Krexion auto-start at login (optional)
;
; NO third-party branding anywhere customer-visible — folder names, service
; names, registry keys, tray tooltip all say "Krexion".
; ════════════════════════════════════════════════════════════════════════

#define AppName        "Krexion"
#define AppPublisher   "Krexion"
#define AppURL         "https://krexion.com"
#define AppExeCore     "krexion-core.exe"
#define AppExeService  "krexion-service.exe"
#define AppExeTray     "krexion-tray.exe"
#define AppLauncherBat "krexion-tray.bat"
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
; AppVersionNumeric is the strict X.X.X.X form (digits + dots only,
; max 4 parts) that Inno Setup's VersionInfoVersion field requires
; (it ultimately becomes the Windows EXE FILEVERSION resource). The
; GitHub Actions workflow derives it from the display tag — e.g.
; "v1.0.5" -> "1.0.5.0", "nightly-…" -> "0.0.0.0". When building
; locally without /DAppVersionNumeric, fall back to "1.0.0.0" so
; Inno Setup doesn't choke on a non-numeric AppVersion like "v1.0.0".
#ifndef AppVersionNumeric
  #define AppVersionNumeric "1.0.0.0"
#endif

[Setup]
AppId={{A4F5C3D2-7E91-4B6E-B0F1-KREXION0001}}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/support
AppUpdatesURL={#AppURL}/releases
DefaultDirName={autopf}\Krexion
DefaultGroupName=Krexion
DisableProgramGroupPage=yes
OutputDir=Output
OutputBaseFilename=Krexion-Setup-{#AppVersion}
Compression=lzma2/ultra
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequired=admin
UninstallDisplayName={#AppName}
SetupIconFile=krexion.ico
UninstallDisplayIcon={app}\bin\{#AppExeCore}
VersionInfoCompany={#AppPublisher}
VersionInfoProductName={#AppName}
VersionInfoVersion={#AppVersionNumeric}
VersionInfoDescription=Krexion Real-User Traffic Engine
CloseApplications=force
RestartApplications=no
WizardImageStretch=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked
Name: "startupTray"; Description: "Start Krexion automatically when Windows starts"; GroupDescription: "Startup:"; Flags: unchecked

[Files]
; Krexion brand icon — used for all Start Menu + Desktop shortcuts so
; the customer sees the Krexion "K" mark everywhere (not the default
; python.exe snake icon embedded in krexion-core.exe).
Source: "krexion.ico"; DestDir: "{app}"; Flags: ignoreversion

; Backend embedded-Python bundle — required
Source: "..\build\dist\krexion-backend.dist\*"; DestDir: "{app}\bin"; Flags: ignoreversion recursesubdirs createallsubdirs

; Service wrapper (NSSM, renamed to krexion-service.exe to hide third-party branding)
Source: "..\build\nssm-portable\nssm.exe"; DestDir: "{app}\bin"; DestName: "{#AppExeService}"; Flags: ignoreversion

; Local database engine (MongoDB Portable, folder renamed to `database`)
Source: "..\build\mongo-portable\*"; DestDir: "{app}\database"; Flags: ignoreversion recursesubdirs createallsubdirs

; Browser engine (Playwright Chromium + WebKit → `browser-engine`)
; WebKit enables iOS Safari-honest dual-engine without manual `playwright install`.
Source: "..\build\chromium-bundle\*"; DestDir: "{app}\browser-engine"; Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist

; v2.9.0 — AdsPower-class Cloak C++ Krexion Kernel (mandatory headed Chromium)
; v2.9.5 — Cloak C++ kernel is MANDATORY (no skipifsourcedoesntexist).
; Build pipeline must stage build\krexion-kernel before compiling the installer.
Source: "..\build\krexion-kernel\*"; DestDir: "{app}\krexion-kernel"; Flags: ignoreversion recursesubdirs createallsubdirs

; Frontend production build — required
Source: "..\build\frontend-build\*"; DestDir: "{app}\frontend"; Flags: ignoreversion recursesubdirs createallsubdirs

; Tray / Dashboard app (PyWebView + pystray, renamed pythonw.exe)
; Bundled inside krexion-backend.dist as krexion-coreapp.exe — surfaced as
; krexion-tray.exe shortcut launcher for the customer.
Source: "..\desktop\krexion_tray_launcher.bat"; DestDir: "{app}"; DestName: "{#AppLauncherBat}"; Flags: ignoreversion skipifsourcedoesntexist
; Diagnostic / visible-console launcher (v1.0.11+). Shipped alongside
; the normal launcher so customers can self-diagnose when the silent
; launcher does nothing - this one keeps the cmd.exe window open and
; runs python.exe (NOT pythonw.exe) so every error is on screen.
; Linked to Start Menu as "Krexion Diagnostic".
Source: "..\desktop\krexion_tray_debug.bat"; DestDir: "{app}"; DestName: "krexion-tray-debug.bat"; Flags: ignoreversion skipifsourcedoesntexist
Source: "..\desktop\*"; DestDir: "{app}\bin\app\desktop"; Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist

; Manifest — optional
Source: "..\build\krexion-manifest.json"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

; Microsoft Visual C++ 2015-2022 Redistributable (x64) — REQUIRED by MongoDB
; 7.0.x. Without it mongod.exe silently crashes with VCRUNTIME140_1.dll
; missing. We ship it inline and run silently if not already present.
; v2.7.66 — install from {app}\prereqs (NOT {tmp}). SAC/WDAC often blocks
; execution from the user temp folder (Inno Error 4551).
Source: "..\build\vcredist\vc_redist.x64.exe"; DestDir: "{app}\prereqs"; Flags: ignoreversion skipifsourcedoesntexist

; Microsoft Edge WebView2 Runtime — REQUIRED by PyWebView on Windows.
Source: "..\build\webview2\MicrosoftEdgeWebview2Setup.exe"; DestDir: "{app}\prereqs"; Flags: ignoreversion skipifsourcedoesntexist

; Adaptive system-specs detector — invoked from the [Run] section to
; write %PROGRAMDATA%\Krexion\system-specs.json the backend reads on
; startup to size its heavy-job semaphore.
Source: "detect-system-specs.ps1"; DestDir: "{app}\prereqs"; Flags: ignoreversion


[Dirs]
; MongoDB data dir lives under %PROGRAMDATA% so NSSM's argv re-assembly
; never breaks on whitespace ("Program Files"). Data survives uninstall
; by default — customer's local DB persists across upgrades.
Name: "{commonappdata}\Krexion\data"; Permissions: users-modify
Name: "{commonappdata}\Krexion\data\db"; Permissions: users-modify
Name: "{app}\logs"
Name: "{commonappdata}\Krexion"; Permissions: users-modify

[Icons]
; v1.0.11 fix: the PRIMARY "Krexion" shortcut MUST launch the native
; PyWebView dashboard, NOT open krexion.com in a browser. Previously
; (v1.0.4 - v1.0.10) ALL Start Menu + desktop icons pointed at
; "{#AppURL}/login" which is just the cloud login page — customers had
; literally no way to re-open the local Krexion window after they
; closed it the first time (the wizard's "Launch Krexion now" post-
; install checkbox was the only entry point, and if they unticked it
; or quit the tray, they were stuck reinstalling). That's the root
; cause of the "software open ni rehta" + "tray mein ni aata" reports.
;
; New layout:
;   * "Krexion"                     -> krexion-tray.bat (native dashboard)
;   * "Krexion (Web)"               -> krexion.com/login (cloud login)
;   * "Krexion Diagnostic"          -> krexion-tray-debug.bat (visible console
;                                      window with full Python output, for
;                                      customer-side debugging when the silent
;                                      launcher does nothing)
;   * "Krexion Logs / Support / Renew / Uninstall" -> unchanged
Name: "{group}\Krexion"; Filename: "{app}\{#AppLauncherBat}"; \
  WorkingDir: "{app}"; IconFilename: "{app}\krexion.ico"; \
  Comment: "Open the Krexion Local Dashboard (fast, offline-capable)"
Name: "{group}\Krexion (Web)"; Filename: "{#AppURL}/login"; \
  IconFilename: "{app}\krexion.ico"; \
  Comment: "Open krexion.com login in your browser"
Name: "{group}\Krexion Diagnostic"; Filename: "{app}\krexion-tray-debug.bat"; \
  WorkingDir: "{app}"; IconFilename: "{app}\krexion.ico"; \
  Comment: "Open Krexion in visible-console debug mode (for troubleshooting)"; \
  Flags: createonlyiffileexists
Name: "{group}\Krexion Support"; Filename: "{#AppURL}/support"; IconFilename: "{app}\krexion.ico"
; The shortcut name MUST NOT contain "/" or "\" — Windows' file system
; treats both as path separators, so a name like "Buy / Renew License"
; makes Inno Setup try to create "Renew License.url" inside a missing
; "Buy " subfolder and abort with "The system cannot find the path
; specified." We use the word "or" (or an en-dash) which is shell-safe
; and reads identically to the user.
Name: "{group}\Buy or Renew License"; Filename: "{#AppURL}/pricing"; IconFilename: "{app}\krexion.ico"
Name: "{group}\Krexion Logs"; Filename: "{app}\logs"; IconFilename: "{app}\krexion.ico"
Name: "{group}\Uninstall Krexion"; Filename: "{uninstallexe}"; IconFilename: "{app}\krexion.ico"
Name: "{autodesktop}\Krexion"; Filename: "{app}\{#AppLauncherBat}"; \
  WorkingDir: "{app}"; IconFilename: "{app}\krexion.ico"; \
  Comment: "Open the Krexion Local Dashboard (fast, offline-capable)"; Tasks: desktopicon

[Registry]
; Auto-start Krexion Dashboard on login (per-user). Launches the
; PyWebView+tray app via a small .bat shim so customer sees Krexion's
; brand and not any python prompt window.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
  ValueType: string; ValueName: "Krexion"; ValueData: """{app}\{#AppLauncherBat}"""; \
  Tasks: startupTray; Flags: uninsdeletevalue

[Run]
; ─── v1.0.22: restart services AFTER we overwrite files ──────────────
; (Services were stopped in PrepareToInstall before file copy — see
; [Code] section below. Here we just make sure they're running.)
; ─── Install Microsoft VC++ 2015-2022 Redistributable (silent, idempotent) ──
; MongoDB 7.0 needs VCRUNTIME140_1.dll which only ships with this runtime.
; /install /quiet /norestart returns exit code 1638 when the runtime is
; already installed (a NEWER version) — that's fine, we accept it.
Filename: "{app}\prereqs\vc_redist.x64.exe"; \
  Parameters: "/install /quiet /norestart"; \
  Flags: runhidden waituntilterminated skipifdoesntexist; \
  StatusMsg: "Installing prerequisites (Visual C++ Runtime)..."

; ─── Install Microsoft Edge WebView2 Runtime (silent, idempotent) ──
Filename: "{app}\prereqs\MicrosoftEdgeWebview2Setup.exe"; \
  Parameters: "/silent /install"; \
  Flags: runhidden waituntilterminated skipifdoesntexist; \
  StatusMsg: "Installing prerequisites (Microsoft Edge WebView2)..."

; ─── Persist the license key the user entered in the wizard ────────────
; The license is written to %PROGRAMDATA%\Krexion\license-key.txt so the
; backend reads it via LICENSE_KEY_FILE env var. Customer never has to
; copy the key to .env manually — installer handles it.
Filename: "{cmd}"; \
  Parameters: "/C echo {code:GetLicenseKey} > ""{commonappdata}\Krexion\license-key.txt"""; \
  Flags: runhidden; StatusMsg: "Saving license key..."; \
  Check: HasLicenseKey

; ─── Persist detected hardware specs ──────────────────────────────────
; Runs detect-system-specs.ps1 which writes
; %PROGRAMDATA%\Krexion\system-specs.json. Backend reads this on
; startup to set adaptive concurrency limits for heavy jobs. The
; PowerShell script handles its own errors and never fails the
; installer — worst case it writes a safe medium-tier fallback.
Filename: "powershell.exe"; \
  Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\prereqs\detect-system-specs.ps1"" -OutDir ""{commonappdata}\Krexion"""; \
  Flags: runhidden waituntilterminated; StatusMsg: "Detecting your PC capacity..."

; ─── Install + start Krexion Database service ──────────────────────────
; Note the dbpath: we point at %PROGRAMDATA%\Krexion\data\db (no
; whitespace) so NSSM's argv re-assembly preserves the value intact.
; The previous v1.0.8 build used {app}\data\db which lives under
; "C:\Program Files\Krexion\data\db" — the space in "Program Files"
; got swallowed by Windows argv parsing and mongod received only
; "C:\Program" as its dbpath, then dumped its help text and exited
; immediately. That was the root cause of every "Krexion Database
; Paused" report.
Filename: "{app}\bin\{#AppExeService}"; \
  Parameters: "install KrexionDatabase ""{app}\database\bin\mongod.exe"" --dbpath {commonappdata}\Krexion\data\db --port 27017 --bind_ip 127.0.0.1 --quiet"; \
  Flags: runhidden; StatusMsg: "Registering Krexion Database service..."

Filename: "{app}\bin\{#AppExeService}"; \
  Parameters: "set KrexionDatabase DisplayName ""Krexion Database"""; \
  Flags: runhidden

Filename: "{app}\bin\{#AppExeService}"; \
  Parameters: "set KrexionDatabase Description ""Krexion local data engine"""; \
  Flags: runhidden

Filename: "{app}\bin\{#AppExeService}"; \
  Parameters: "set KrexionDatabase Start SERVICE_AUTO_START"; \
  Flags: runhidden

; Diagnostic logging — captures mongod stdout/stderr to {app}\logs\
; (without these, if mongod crashes the customer has zero visibility)
Filename: "{app}\bin\{#AppExeService}"; \
  Parameters: "set KrexionDatabase AppDirectory ""{app}\database\bin"""; \
  Flags: runhidden

Filename: "{app}\bin\{#AppExeService}"; \
  Parameters: "set KrexionDatabase AppStdout ""{app}\logs\mongod.stdout.log"""; \
  Flags: runhidden

Filename: "{app}\bin\{#AppExeService}"; \
  Parameters: "set KrexionDatabase AppStderr ""{app}\logs\mongod.stderr.log"""; \
  Flags: runhidden

; Auto-restart on crash (NSSM AppExit Default Restart) + 5s cooldown
Filename: "{app}\bin\{#AppExeService}"; \
  Parameters: "set KrexionDatabase AppExit Default Restart"; \
  Flags: runhidden

Filename: "{app}\bin\{#AppExeService}"; \
  Parameters: "set KrexionDatabase AppRestartDelay 5000"; \
  Flags: runhidden

; Rotate log files at 10 MB to prevent disk fill on long-running installs
Filename: "{app}\bin\{#AppExeService}"; \
  Parameters: "set KrexionDatabase AppRotateFiles 1"; \
  Flags: runhidden

Filename: "{app}\bin\{#AppExeService}"; \
  Parameters: "set KrexionDatabase AppRotateBytes 10485760"; \
  Flags: runhidden

Filename: "{app}\bin\{#AppExeService}"; \
  Parameters: "start KrexionDatabase"; \
  Flags: runhidden; StatusMsg: "Starting Krexion Database..."

; ─── Install + start Krexion Backend service ───────────────────────────
; Service runs via krexion-core.exe (white-labelled python.exe copy) so
; the customer's Task Manager + Services.msc only ever shows "Krexion".
Filename: "{app}\bin\{#AppExeService}"; \
  Parameters: "install KrexionBackend ""{app}\bin\{#AppExeCore}"" -m uvicorn server:app --host 127.0.0.1 --port 8001"; \
  Flags: runhidden; StatusMsg: "Registering Krexion Backend service..."

Filename: "{app}\bin\{#AppExeService}"; \
  Parameters: "set KrexionBackend DisplayName ""Krexion Backend"""; \
  Flags: runhidden

Filename: "{app}\bin\{#AppExeService}"; \
  Parameters: "set KrexionBackend Description ""Krexion core service — Real-User Traffic engine"""; \
  Flags: runhidden

Filename: "{app}\bin\{#AppExeService}"; \
  Parameters: "set KrexionBackend Start SERVICE_AUTO_START"; \
  Flags: runhidden

; NSSM's `AppEnvironmentExtra` accepts multiple "NAME=VALUE" arguments
; in one call, but Windows command-line parsing splits on spaces — so
; values containing spaces (notably PLAYWRIGHT_BROWSERS_PATH when {app}
; resolves to "C:\Program Files\Krexion") would be torn into separate
; argv slots and NSSM would receive garbage. Result: NO env vars get
; set, the Python backend crashes with "MONGO_URL environment variable
; is required!", and NSSM throttles the service into the "Paused"
; state. We wrap EVERY "NAME=VALUE" pair in literal quotes (Inno Setup
; doubles "" -> ") so each one arrives at NSSM as a single argv entry,
; regardless of the install path the customer picks.
;
; 2026-01 (v2.1.82) — PYTHONIOENCODING=utf-8 + PYTHONUTF8=1 added.
; Without these two the Windows Service has no console attached and
; Python's sys.stdout falls back to cp1252, so the FIRST print() with
; a non-ASCII char (the "⚠️" warning around server.py:~1620 for the
; JWT_SECRET_KEY / ADMIN_PASSWORD defaults) crashes the backend on
; boot → "KrexionBackend PAUSED / start failed" in the dashboard.
; server.py also self-heals via sys.stdout.reconfigure(), but setting
; these here means the very first byte written to stdout is already
; UTF-8, which is how the Electron build already runs the backend.
Filename: "{app}\bin\{#AppExeService}"; \
  Parameters: "set KrexionBackend AppEnvironmentExtra ""MONGO_URL=mongodb://127.0.0.1:27017"" ""DB_NAME=krexion"" ""KREXION_MODE=native"" ""KREXION_BUILD_TYPE=binary"" ""KREXION_CLOUD_URL={#AppURL}"" ""KREXION_SYNC_STATUS_FILE={commonappdata}\Krexion\sync-status.json"" ""PLAYWRIGHT_BROWSERS_PATH={app}\browser-engine"" ""KREXION_KERNEL_PATH={app}\krexion-kernel\chrome.exe"" ""CLOAKBROWSER_BINARY_PATH={app}\krexion-kernel\chrome.exe"" ""STRICT_CLOUD_HEAVY_BLOCK=false"" ""LICENSE_KEY_FILE={commonappdata}\Krexion\license-key.txt"" ""PYTHONIOENCODING=utf-8"" ""PYTHONUTF8=1"""; \
  Flags: runhidden

Filename: "{app}\bin\{#AppExeService}"; \
  Parameters: "set KrexionBackend AppDirectory ""{app}\bin\app"""; \
  Flags: runhidden

Filename: "{app}\bin\{#AppExeService}"; \
  Parameters: "set KrexionBackend AppStdout ""{app}\logs\backend.stdout.log"""; \
  Flags: runhidden

Filename: "{app}\bin\{#AppExeService}"; \
  Parameters: "set KrexionBackend AppStderr ""{app}\logs\backend.stderr.log"""; \
  Flags: runhidden

; Auto-restart on crash (NSSM AppExit Default Restart) + 5s cooldown
Filename: "{app}\bin\{#AppExeService}"; \
  Parameters: "set KrexionBackend AppExit Default Restart"; \
  Flags: runhidden

Filename: "{app}\bin\{#AppExeService}"; \
  Parameters: "set KrexionBackend AppRestartDelay 5000"; \
  Flags: runhidden

; Rotate log files at 10 MB
Filename: "{app}\bin\{#AppExeService}"; \
  Parameters: "set KrexionBackend AppRotateFiles 1"; \
  Flags: runhidden

Filename: "{app}\bin\{#AppExeService}"; \
  Parameters: "set KrexionBackend AppRotateBytes 10485760"; \
  Flags: runhidden

; ── v2.1.81 — Windows service dependency ─────────────────────────────
; Force KrexionBackend to wait for KrexionDatabase to reach RUNNING
; before it tries to boot. Without this, on Windows startup the
; backend service races MongoDB and always loses the first ~5-10 s
; (mongod takes longer to open its data files than uvicorn takes to
; import + connect). Backend crashes on refused DB connect, NSSM
; restarts it after AppRestartDelay=5000, sometimes the loop settles
; and sometimes NSSM's throttle kicks in and the service ends up
; STOPPED — which is exactly the "Backend has never responded since
; Krexion started" state the customer's dashboard was reporting.
; sc.exe uses `depend= <name>` (mind the space after `=`).
Filename: "{sys}\sc.exe"; \
  Parameters: "config KrexionBackend depend= KrexionDatabase"; \
  Flags: runhidden

Filename: "{app}\bin\{#AppExeService}"; \
  Parameters: "start KrexionBackend"; \
  Flags: runhidden; StatusMsg: "Starting Krexion Backend..."

; ─── Auto-launch desktop dashboard at finish ──────────────────────────
; The dashboard window stays open until the customer right-clicks the
; tray icon → Quit. Closing the X minimises to tray. Polls local
; backend at 127.0.0.1:8001 for live CPU/RAM/job stats and shows
; auto-update banner when admin publishes a new release.
Filename: "{app}\{#AppLauncherBat}"; Flags: nowait postinstall skipifsilent skipifdoesntexist; \
  Description: "Launch Krexion now"
Filename: "{#AppURL}/login"; Flags: shellexec postinstall skipifsilent; \
  Description: "Open Krexion dashboard at krexion.com"

[UninstallRun]
; Stop + remove services BEFORE files are deleted
Filename: "{app}\bin\{#AppExeService}"; Parameters: "stop KrexionBackend"; Flags: runhidden; RunOnceId: "StopBackend"
Filename: "{app}\bin\{#AppExeService}"; Parameters: "remove KrexionBackend confirm"; Flags: runhidden; RunOnceId: "RemoveBackend"
Filename: "{app}\bin\{#AppExeService}"; Parameters: "stop KrexionDatabase"; Flags: runhidden; RunOnceId: "StopDatabase"
Filename: "{app}\bin\{#AppExeService}"; Parameters: "remove KrexionDatabase confirm"; Flags: runhidden; RunOnceId: "RemoveDatabase"

[UninstallDelete]
; Logs go on uninstall. The entire %PROGRAMDATA%\Krexion tree
; (license + data + system-specs) is PRESERVED on uninstall by
; default — that means a reinstall picks up where the customer left
; off, with their MongoDB data and license intact. Customer can
; manually delete `C:\ProgramData\Krexion` if they want a full purge.
Type: filesandordirs; Name: "{app}\logs"

[Code]
var
  LicensePage: TInputQueryWizardPage;

procedure InitializeWizard;
begin
  // Custom wizard page — collect the customer's license key BEFORE
  // installation begins. The value is later piped into license-key.txt
  // by the [Run] section.
  //
  // 2026-06 — License is now MANDATORY. The customer cannot click
  // Next on this page until a non-empty key in the canonical
  // KRX-XXXX-XXXX-XXXX-XXXX shape is entered (enforced in
  // NextButtonClick below). Removes the prior "leave blank and add
  // later" escape hatch that let paid-only software be installed by
  // unverified visitors.
  LicensePage := CreateInputQueryPage(
    wpWelcome,
    'License Activation (required)',
    'Enter your Krexion license key',
    'Paste the KRX-XXXX-XXXX-XXXX-XXXX key from your purchase email.' + #13#10 +
    'This step is required — you cannot continue without a valid-shaped key.' + #13#10 +
    'If you do not have one yet, please complete checkout at https://krexion.com/pricing.'
  );
  LicensePage.Add('License key:', False);
  LicensePage.Values[0] := '';
end;

function GetLicenseKey(Param: string): string;
var
  Raw: string;
begin
  Raw := Trim(LicensePage.Values[0]);
  // Strip stray whitespace + uppercase so it matches the canonical
  // KRX-XXXX-XXXX-XXXX-XXXX format the backend expects.
  StringChangeEx(Raw, ' ', '', True);
  Result := Uppercase(Raw);
end;

function HasLicenseKey: Boolean;
begin
  Result := Length(GetLicenseKey('')) > 0;
end;

// 2026-06 — Validate the shape KRX-XXXX-XXXX-XXXX-XXXX. We do *not*
// hit the network from inside the installer (cust may have spotty
// connectivity / corp proxy) — the local backend re-validates the
// key against the cloud on first start, and the dashboard will show
// a clear "License invalid" banner if the key turns out to be fake.
// Inno Setup has no native regex, so we walk the string by hand.
function IsValidLicenseShape(K: string): Boolean;
var
  i, Seg, SegLen: Integer;
  Ch: Char;
begin
  Result := False;
  // Canonical: KRX-XXXX-XXXX-XXXX-XXXX  (3 + 4*(1+4) = 23 chars,
  // 4 dashes, only A-Z 0-9 inside segments)
  if Length(K) <> 23 then Exit;
  if Copy(K, 1, 4) <> 'KRX-' then Exit;
  Seg := 0;
  SegLen := 0;
  for i := 5 to Length(K) do
  begin
    Ch := K[i];
    if Ch = '-' then
    begin
      if SegLen <> 4 then Exit;
      SegLen := 0;
      Seg := Seg + 1;
    end
    else if ((Ch >= 'A') and (Ch <= 'Z')) or ((Ch >= '0') and (Ch <= '9')) then
    begin
      SegLen := SegLen + 1;
      if SegLen > 4 then Exit;
    end
    else
      Exit;
  end;
  // Last segment must also be exactly 4 chars
  if SegLen <> 4 then Exit;
  // We must have seen exactly 3 dash-separated segments after KRX-
  if Seg <> 3 then Exit;
  Result := True;
end;

// Inno Setup callback: invoked when the user clicks Next on any
// wizard page. Returning False keeps them on the page (use this to
// block forward navigation when their license key is missing or
// malformed). We only gate the LicensePage; every other page passes
// through unchanged.
function NextButtonClick(CurPageID: Integer): Boolean;
var
  K: string;
begin
  Result := True;
  if Assigned(LicensePage) and (CurPageID = LicensePage.ID) then
  begin
    K := GetLicenseKey('');
    if Length(K) = 0 then
    begin
      MsgBox(
        'A license key is required to install Krexion.' + #13#10 + #13#10 +
        'Paste the KRX-XXXX-XXXX-XXXX-XXXX key from your purchase email.' + #13#10 +
        'If you have not purchased yet, visit https://krexion.com/pricing.',
        mbError, MB_OK
      );
      Result := False;
      Exit;
    end;
    if not IsValidLicenseShape(K) then
    begin
      MsgBox(
        'That key does not look right.' + #13#10 + #13#10 +
        'Expected format:  KRX-XXXX-XXXX-XXXX-XXXX' + #13#10 +
        '(letters A-Z and digits 0-9, four blocks of four, separated by dashes).' + #13#10 + #13#10 +
        'Please copy the key exactly as it appears in your purchase email.',
        mbError, MB_OK
      );
      Result := False;
      Exit;
    end;
  end;
end;

function InitializeSetup(): Boolean;
begin
  // Future hook for OS version / disk space pre-flight checks.
  Result := True;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  // v1.0.22 FIX: stop existing Krexion services + processes BEFORE
  // file copy. Without this, over-installing on a running v1.0.17
  // left the OLD Python process in memory holding the OLD code —
  // the customer "installed v1.0.21" but the dashboard kept showing
  // v1.0.17 and heartbeats kept using the stale logic.
  //
  // We swallow exit codes via cmd /C and ignore failures: the
  // services / processes may simply not exist on a fresh install.
  Exec(ExpandConstant('{cmd}'),
       '/C sc stop KrexionBackend',
       '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec(ExpandConstant('{cmd}'),
       '/C sc stop KrexionDatabase',
       '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  // Kill any leftover tray / dashboard / Python launcher processes
  // that might hold open desktop\*.py via PyWebView import.
  Exec(ExpandConstant('{cmd}'),
       '/C taskkill /F /IM krexion-coreapp.exe /T',
       '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec(ExpandConstant('{cmd}'),
       '/C taskkill /F /IM krexion-tray.exe /T',
       '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec(ExpandConstant('{cmd}'),
       '/C taskkill /F /IM krexion-core.exe /T',
       '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  // v2.7.22 — wipe stale frontend bundle before copying the new one.
  // Without this, locked/untracked files from a prior install can leave
  // the customer on an old React build even when backend VERSION updated.
  Exec(ExpandConstant('{cmd}'),
       '/C if exist "' + ExpandConstant('{app}') + '\frontend" rmdir /S /Q "' + ExpandConstant('{app}') + '\frontend"',
       '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  // Give the OS 3 s to release file handles before [Files] starts.
  Exec(ExpandConstant('{cmd}'),
       '/C timeout /t 3 /nobreak',
       '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Result := '';
end;
