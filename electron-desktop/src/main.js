// ─────────────────────────────────────────────────────────────────────────────
// Krexion Desktop — Electron main process
// ─────────────────────────────────────────────────────────────────────────────
// Boots a fully-local Krexion stack on the customer's PC:
//
//   1. Starts a bundled portable MongoDB on 127.0.0.1:27117 with dbpath in
//      %APPDATA%\Krexion-Desktop\db
//   2. Starts the embedded-Python FastAPI backend on 127.0.0.1:8088 with
//      MONGO_URL pointing at the local MongoDB.
//   3. Loads the production React frontend (baked with REACT_APP_BACKEND_URL=
//      http://127.0.0.1:8088) inside a Chromium BrowserWindow.
//
// Heavy workload data stays 100% on the customer's machine. Only license
// validation and release checks reach krexion.com (handled inside the
// backend's existing license_module / releases_module).
//
// This file is intentionally additive — it does NOT modify the existing
// Inno-Setup installer or web app. Both ship side-by-side.
// ─────────────────────────────────────────────────────────────────────────────

const { app, BrowserWindow, Menu, Tray, dialog, shell, nativeImage, protocol, net, ipcMain } = require('electron');
const path = require('path');
const fs = require('fs');
const { spawn } = require('child_process');
const http = require('http');
const { pathToFileURL } = require('url');
const log = require('electron-log/main');
const { autoUpdater } = require('electron-updater');

log.initialize();
log.transports.file.level = 'info';
log.transports.console.level = 'info';

// ── Paths ────────────────────────────────────────────────────────────────────
// In packaged builds, electron-builder unpacks `resources/krexion/**` to:
//   <app-root>/resources/krexion/...
// In dev, we look in ../resources/krexion (populated by prepare-resources.js).
const resourcesRoot = app.isPackaged
  ? path.join(process.resourcesPath, 'krexion')
  : path.join(__dirname, '..', 'resources', 'krexion');

const pythonExe = path.join(resourcesRoot, 'python', 'python.exe');
const backendDir = path.join(resourcesRoot, 'backend');
const backendEntry = path.join(backendDir, 'server.py');
const mongoExe = path.join(resourcesRoot, 'mongodb', 'bin', 'mongod.exe');
const frontendDir = path.join(resourcesRoot, 'frontend');
const iconPath = path.join(resourcesRoot, 'icon.ico');

const userDataDir = app.getPath('userData');
const dbDir = path.join(userDataDir, 'db');
const logsDir = path.join(userDataDir, 'logs');
fs.mkdirSync(dbDir, { recursive: true });
fs.mkdirSync(logsDir, { recursive: true });

const MONGO_PORT = 27117;
const BACKEND_PORT = 8088;
const MONGO_URL = `mongodb://127.0.0.1:${MONGO_PORT}`;
const DB_NAME = 'krexion_local';
const BACKEND_URL = `http://127.0.0.1:${BACKEND_PORT}`;

let mongoProc = null;
let backendProc = null;
let mainWindow = null;
let splashWindow = null;
let tray = null;
let isQuitting = false;

// ── Single-instance lock so customers cannot launch 2 Krexion Desktops ──────
const gotTheLock = app.requestSingleInstanceLock();
if (!gotTheLock) {
  app.quit();
  return;
}
app.on('second-instance', () => {
  if (mainWindow) {
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.focus();
  }
});

// ── Register custom `app://` protocol as PRIVILEGED ──────────────────────────
// Why: the React frontend uses BrowserRouter (HTML5 history API). Under the
// `file://` protocol, `window.location.pathname` becomes something like
//   /C:/Program%20Files/Krexion%20Desktop/resources/krexion/frontend/index.html
// which doesn't match any of the app's React routes ("/", "/login", etc.)
// — so the route outlet renders empty and the customer sees a black window
// with only the floating DebugConsole button in the bottom-right.
//
// Custom protocols give us a clean URL space we control. We register `app`
// here with `standard: true` (URL parsing follows http rules) and
// `secure: true` (treated as a secure origin so service workers, crypto,
// localStorage, etc. behave like https). `supportFetchAPI: true` lets the
// React app's own fetch() calls work, although note that fetches to the
// FastAPI backend on http://127.0.0.1:8088 still go over normal HTTP and
// rely on the backend's CORS middleware (which is already set to '*').
//
// MUST be called BEFORE app.whenReady(). The actual request handler is
// installed inside whenReady() — see `registerAppProtocol()`.
protocol.registerSchemesAsPrivileged([
  {
    scheme: 'app',
    privileges: {
      standard: true,
      secure: true,
      supportFetchAPI: true,
      stream: true,
      corsEnabled: true,
    },
  },
]);

// ── Helpers ──────────────────────────────────────────────────────────────────
function logFileStream(name) {
  return fs.createWriteStream(path.join(logsDir, name), { flags: 'a' });
}

function waitForHttp(url, timeoutMs = 60000) {
  return new Promise((resolve, reject) => {
    const start = Date.now();
    const tick = () => {
      const req = http.get(url, { timeout: 2000 }, (res) => {
        res.resume();
        if (res.statusCode && res.statusCode < 500) return resolve();
        if (Date.now() - start > timeoutMs) return reject(new Error(`Timeout waiting for ${url}`));
        setTimeout(tick, 1000);
      });
      req.on('error', () => {
        if (Date.now() - start > timeoutMs) return reject(new Error(`Timeout waiting for ${url}`));
        setTimeout(tick, 1000);
      });
      req.on('timeout', () => {
        req.destroy();
        if (Date.now() - start > timeoutMs) return reject(new Error(`Timeout waiting for ${url}`));
        setTimeout(tick, 1000);
      });
    };
    tick();
  });
}

function waitForTcp(host, port, timeoutMs = 60000) {
  return new Promise((resolve, reject) => {
    const net = require('net');
    const start = Date.now();
    const tick = () => {
      const socket = new net.Socket();
      socket.setTimeout(2000);
      socket.once('connect', () => { socket.destroy(); resolve(); });
      socket.once('timeout', () => { socket.destroy(); retry(); });
      socket.once('error', () => { socket.destroy(); retry(); });
      socket.connect(port, host);
      function retry() {
        if (Date.now() - start > timeoutMs) return reject(new Error(`Timeout waiting for ${host}:${port}`));
        setTimeout(tick, 1000);
      }
    };
    tick();
  });
}

// ── MongoDB ──────────────────────────────────────────────────────────────────
function startMongo() {
  log.info(`[mongo] starting on 127.0.0.1:${MONGO_PORT}, dbpath=${dbDir}`);
  mongoProc = spawn(
    mongoExe,
    [
      '--dbpath', dbDir,
      '--port', String(MONGO_PORT),
      '--bind_ip', '127.0.0.1',
      '--noauth',
      '--quiet'
    ],
    {
      cwd: path.dirname(mongoExe),
      windowsHide: true,
    }
  );
  const out = logFileStream('mongo.log');
  mongoProc.stdout.pipe(out);
  mongoProc.stderr.pipe(out);
  mongoProc.on('exit', (code) => {
    log.warn(`[mongo] exited code=${code}`);
    if (!isQuitting) {
      dialog.showErrorBox('Krexion Desktop', 'Local database stopped unexpectedly. Please restart Krexion Desktop.');
      app.quit();
    }
  });
  return waitForTcp('127.0.0.1', MONGO_PORT, 45000);
}

// ── Python backend ───────────────────────────────────────────────────────────
function startBackend() {
  log.info(`[backend] starting on 127.0.0.1:${BACKEND_PORT}`);
  const env = {
    ...process.env,
    MONGO_URL,
    DB_NAME,
    // 2026-02 — v2.1.13: report 'native' so the React shell switches to
    // the AdsPower-style NativeShell (sidebar + topbar + title-bar
    // chrome) only inside the packaged desktop app. The cloud
    // (krexion.com) keeps its existing DashboardLayout untouched
    // because it sets KREXION_MODE=cloud. Backend treats 'native' the
    // same as 'local' for every other purpose (IS_CLOUD is False).
    KREXION_MODE: 'native',
    KREXION_DESKTOP: '1',
    // 2026-02 — v2.1.15: Cloud-Auth bridge. The embedded Python
    // backend's cloud-proxy middleware forwards /api/auth/*,
    // /api/admin/*, /api/license/*, /api/links/* to this URL.
    // Everything else (clicks, RUT, conversions, automation) is
    // handled locally. See cloud_proxy_module.py.
    KREXION_CLOUD_URL: process.env.KREXION_CLOUD_URL || 'https://krexion.com',
    PORT: String(BACKEND_PORT),
    HOST: '127.0.0.1',
    // Help embedded Python find site-packages under <python>\Lib\site-packages
    PYTHONHOME: path.join(resourcesRoot, 'python'),
    PYTHONPATH: [
      backendDir,
      path.join(resourcesRoot, 'python', 'Lib', 'site-packages'),
    ].join(path.delimiter),
    PYTHONIOENCODING: 'utf-8',
    PYTHONUTF8: '1',
    PYTHONDONTWRITEBYTECODE: '1',
    // 2026-06-11 (v2.1.40): point Playwright at the bundled Chromium
    // shipped under resources/krexion/chromium/. Without this the
    // backend would look in %USERPROFILE%\AppData\Local\ms-playwright
    // (electron-updater installs are per-user so that path is empty)
    // and every Browser-Profile launch / RUT job would fail with
    // "Executable doesn't exist at ... \chromium-headless-shell-...".
    PLAYWRIGHT_BROWSERS_PATH: path.join(resourcesRoot, 'chromium'),
    // v2.9.0 — AdsPower-class Cloak C++ kernel (mandatory for headed profiles)
    KREXION_KERNEL_PATH: path.join(
      resourcesRoot,
      'krexion-kernel',
      process.platform === 'win32' ? 'chrome.exe' : 'chrome'
    ),
    CLOAKBROWSER_BINARY_PATH: path.join(
      resourcesRoot,
      'krexion-kernel',
      process.platform === 'win32' ? 'chrome.exe' : 'chrome'
    ),
  };

  // Prefer uvicorn directly; server.py exposes `app` as a FastAPI instance.
  backendProc = spawn(
    pythonExe,
    [
      '-m', 'uvicorn',
      'server:app',
      '--host', '127.0.0.1',
      '--port', String(BACKEND_PORT),
      '--no-access-log',
    ],
    {
      cwd: backendDir,
      env,
      windowsHide: true,
    }
  );
  const out = logFileStream('backend.log');
  backendProc.stdout.pipe(out);
  backendProc.stderr.pipe(out);
  backendProc.on('exit', (code) => {
    log.warn(`[backend] exited code=${code}`);
    if (!isQuitting) {
      dialog.showErrorBox('Krexion Desktop', 'Local backend stopped unexpectedly. Please restart Krexion Desktop.');
      app.quit();
    }
  });
  return waitForHttp(`${BACKEND_URL}/api/`, 90000).catch(() =>
    waitForHttp(`${BACKEND_URL}/docs`, 30000)
  );
}

// ── Windows ──────────────────────────────────────────────────────────────────
function createSplash() {
  splashWindow = new BrowserWindow({
    width: 520,
    height: 320,
    frame: false,
    resizable: false,
    alwaysOnTop: true,
    transparent: false,
    show: true,
    icon: fs.existsSync(iconPath) ? iconPath : undefined,
    webPreferences: { contextIsolation: true, nodeIntegration: false },
  });
  splashWindow.loadFile(path.join(__dirname, 'splash.html'));
  // Inject the real installed app version into the splash footer so the
  // customer never sees a stale hard-coded "v2.1.8" while they're actually
  // running, say, v2.1.12. The HTML side has <span id="appVersion">…</span>
  // as a placeholder; we replace its textContent right after the page
  // loads. Failure here is non-fatal — the splash still functions even
  // if the inject misses.
  splashWindow.webContents.once('did-finish-load', () => {
    try {
      const v = app.getVersion();
      splashWindow.webContents.executeJavaScript(
        `(() => { const el = document.getElementById('appVersion'); if (el) el.textContent = 'v${v}'; })();`
      ).catch((err) => log.warn('[splash] version inject failed (non-fatal)', err?.message || err));
    } catch (err) {
      log.warn('[splash] version inject error', err);
    }
  });
}

function createMainWindow() {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 1100,
    minHeight: 700,
    show: false,
    backgroundColor: '#0b0b0d',
    icon: fs.existsSync(iconPath) ? iconPath : undefined,
    title: 'Krexion Desktop',
    autoHideMenuBar: true,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      preload: path.join(__dirname, 'preload.js'),
      // Why these two flags matter — login-hang fix:
      //
      // We register the `app://` protocol as `secure: true` (so the React
      // app gets a secure-context origin and things like crypto.subtle /
      // localStorage / service-workers behave correctly). Chromium then
      // treats it as an https-equivalent origin.
      //
      // The frontend's API calls go to `http://127.0.0.1:8088/api/...`,
      // which from a "secure" origin is treated as MIXED CONTENT. Most
      // modern Chromium versions allow http://localhost and http://127.0.0.1
      // from secure contexts (they're considered "potentially trustworthy"),
      // BUT Electron's local-resource handling can still surprise the
      // request — most commonly observable as a login form stuck on
      // "Signing in..." forever because the POST never completes.
      //
      // `allowRunningInsecureContent: true` explicitly unblocks the
      // http://127.0.0.1 calls from our secure `app://` origin, and
      // `webSecurity: true` is left on so we don't broaden any other
      // browser security boundary. Net effect: login + every other
      // backend API call now resolves promptly instead of hanging.
      allowRunningInsecureContent: true,
      webSecurity: true,
    },
  });

  // Load via our custom `app://` protocol (see registerAppProtocol below).
  //
  // We deliberately do NOT use `mainWindow.loadFile(indexHtml)` here even
  // though the file exists — under `file://`, React's BrowserRouter sees
  // a pathname like "/C:/Program Files/Krexion Desktop/..." which matches
  // no defined route, leaving the user with a black window. Loading via
  // `app://krexion/` gives the SPA a clean root URL ("/") that
  // BrowserRouter happily resolves to PublicHome → /login or /dashboard.
  //
  // If the protocol handler isn't ready (very unlikely — we register it
  // before this window is ever created) we fall back to the FastAPI
  // backend root.
  if (fs.existsSync(path.join(frontendDir, 'index.html'))) {
    mainWindow.loadURL('app://krexion/');
  } else {
    mainWindow.loadURL(`${BACKEND_URL}/`);
  }

  // v2.1.22 — Mandatory login on every cold launch.
  // Customer requirement: "login b har bar mange ta k automatically login
  // na ho jay jis user k pas login ho os ka wahi login kr sake".
  // We clear localStorage.token + user as soon as the page DOM is ready
  // so the React PrivateRoute redirects to /login. This runs ONCE per
  // app launch (not on internal route navigations) because did-finish-load
  // for the main URL fires once. The cleared item only removes auth —
  // user's stored preferences (sidebar collapse, theme, etc.) survive.
  mainWindow.webContents.once('did-finish-load', () => {
    mainWindow.webContents.executeJavaScript(`
      try {
        localStorage.removeItem('token');
        localStorage.removeItem('user');
        // Surface the new state to React listeners
        window.dispatchEvent(new Event('storage'));
      } catch (e) { /* localStorage may be unavailable on file:// — safe to ignore */ }
    `).catch(() => {});
  });

  // Surface page-load failures (eg. protocol not registered, frontend
  // directory missing, etc.) into the log file so support can debug a
  // customer's machine remotely from %APPDATA%\Krexion-Desktop\logs.
  mainWindow.webContents.on('did-fail-load', (_evt, errorCode, errorDescription, validatedURL) => {
    log.error(`[window] did-fail-load url=${validatedURL} code=${errorCode} desc=${errorDescription}`);
  });
  mainWindow.webContents.on('render-process-gone', (_evt, details) => {
    log.error(`[window] render-process-gone reason=${details.reason} exitCode=${details.exitCode}`);
  });

  mainWindow.once('ready-to-show', () => {
    mainWindow.show();
    if (splashWindow) {
      splashWindow.destroy();
      splashWindow = null;
    }
  });

  // External links → default browser, not inside the Electron shell.
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith('http://127.0.0.1') || url.startsWith(BACKEND_URL)) {
      return { action: 'allow' };
    }
    shell.openExternal(url);
    return { action: 'deny' };
  });

  mainWindow.on('close', (e) => {
    if (!isQuitting) {
      e.preventDefault();
      mainWindow.hide();
    }
  });
}

function createTray() {
  const image = fs.existsSync(iconPath)
    ? nativeImage.createFromPath(iconPath)
    : nativeImage.createEmpty();
  tray = new Tray(image);
  tray.setToolTip('Krexion Desktop');
  const menu = Menu.buildFromTemplate([
    { label: 'Open Krexion', click: () => mainWindow && mainWindow.show() },
    { label: 'Check for Updates…', click: () => checkForUpdatesManual() },
    { type: 'separator' },
    {
      // Lets the customer pop the Chromium DevTools open without needing
      // to know the F12 / Ctrl+Shift+I shortcut. Support uses this to
      // ask customers to share the Console / Network tab when something
      // misbehaves (e.g. login hang, dashboard not loading).
      label: 'Toggle DevTools',
      click: () => {
        if (!mainWindow) return;
        if (mainWindow.webContents.isDevToolsOpened()) {
          mainWindow.webContents.closeDevTools();
        } else {
          mainWindow.webContents.openDevTools({ mode: 'detach' });
        }
      },
    },
    { label: 'Open Logs Folder', click: () => shell.openPath(logsDir) },
    {
      // Direct shortcut to https://krexion.com/pricing for renewals,
      // upgrades, or buying additional seats. Opens in the customer's
      // default browser (not inside the Electron window) so they keep
      // their Krexion Desktop session running while they pay.
      label: 'Buy / Renew License…',
      click: () => shell.openExternal('https://krexion.com/pricing'),
    },
    { type: 'separator' },
    { label: 'Quit Krexion', click: () => { isQuitting = true; app.quit(); } },
  ]);
  tray.setContextMenu(menu);
  tray.on('click', () => mainWindow && mainWindow.show());
}

// ── Auto-updater (electron-updater + GitHub Releases) ────────────────────────
// Customer-side update flow:
//   1. On every launch (~3 s after the main window is visible) we silently
//      ask GitHub for the latest published release manifest (latest.yml).
//   2. If a newer version exists, electron-updater background-downloads
//      the new NSIS installer to a temp cache. No UI is shown during the
//      download — the customer keeps working.
//   3. When the download finishes we show ONE non-blocking dialog:
//      "Restart now to install vX.Y.Z?" with Restart / Later buttons.
//      "Later" defers the install to the next normal app quit (handled by
//      electron-updater automatically).
//   4. Errors are logged to %APPDATA%\Krexion-Desktop\logs but NEVER
//      shown to the customer. A missing/blocked github.com or a corrupt
//      release manifest must not crash or even visibly degrade the app.
//
// Safety guards:
//   • Auto-update is DISABLED when running unpackaged (dev / source runs).
//   • Manual "Check for Updates…" tray menu entry triggers the same flow
//     and shows a small confirmation when no update is available — so the
//     admin / user can verify connectivity.
//   • Repo is PUBLIC, so no GH_TOKEN is needed on the customer side.

let updateCheckInFlight = false;
let manualCheckTriggered = false;

function configureAutoUpdater() {
  // electron-log integration → updater writes to the same log file as the
  // rest of the app (%APPDATA%\Krexion-Desktop\logs\main.log).
  autoUpdater.logger = log;
  autoUpdater.logger.transports.file.level = 'info';

  // Default behavior: download silently in background, prompt before
  // installing. We override defaults below to make the prompt nicer.
  autoUpdater.autoDownload = true;
  autoUpdater.autoInstallOnAppQuit = true;
  autoUpdater.allowDowngrade = false;
  autoUpdater.allowPrerelease = false;

  autoUpdater.on('checking-for-update', () => {
    log.info('[updater] checking for update…');
  });

  autoUpdater.on('update-available', (info) => {
    log.info(`[updater] update available: v${info?.version} (current v${app.getVersion()})`);
    updateCheckInFlight = false;
  });

  autoUpdater.on('update-not-available', (info) => {
    log.info(`[updater] no update available (latest v${info?.version})`);
    updateCheckInFlight = false;
    if (manualCheckTriggered) {
      manualCheckTriggered = false;
      if (mainWindow) {
        dialog.showMessageBox(mainWindow, {
          type: 'info',
          buttons: ['OK'],
          title: 'Krexion Desktop',
          message: 'You\'re on the latest version.',
          detail: `Krexion Desktop v${app.getVersion()} is up to date.`,
        }).catch(() => {});
      }
    }
  });

  autoUpdater.on('download-progress', (p) => {
    log.info(`[updater] downloading ${p.percent?.toFixed(1)}% (${p.transferred}/${p.total})`);
  });

  autoUpdater.on('update-downloaded', (info) => {
    log.info(`[updater] update downloaded: v${info?.version}`);
    updateCheckInFlight = false;
    if (!mainWindow) return;
    // Non-blocking prompt — customer can keep working if they pick "Later".
    dialog.showMessageBox(mainWindow, {
      type: 'info',
      buttons: ['Restart and install', 'Later'],
      defaultId: 0,
      cancelId: 1,
      title: 'Krexion Desktop — update ready',
      message: `Krexion Desktop v${info?.version} is ready to install.`,
      detail:
        'A new version has been downloaded in the background.\n' +
        'You can restart now to install it, or keep working — the update ' +
        'will be applied automatically the next time you quit Krexion Desktop.',
      noLink: true,
    }).then((result) => {
      if (result.response === 0) {
        log.info('[updater] customer chose "Restart and install"');
        isQuitting = true;
        // quitAndInstall handles closing the main window and replacing
        // the running binary with the new installer.
        try {
          autoUpdater.quitAndInstall(false, true);
        } catch (err) {
          log.error('[updater] quitAndInstall failed', err);
        }
      } else {
        log.info('[updater] customer chose "Later" — install on next quit');
      }
    }).catch((err) => log.error('[updater] dialog error', err));
  });

  autoUpdater.on('error', (err) => {
    // Customers MUST NOT see scary errors. We just log and move on.
    // Common reasons: no internet, GitHub rate-limit, release without
    // a latest.yml manifest. The app keeps working at the current version.
    updateCheckInFlight = false;
    log.error('[updater] error (suppressed from UI)', err?.message || err);
    if (manualCheckTriggered) {
      manualCheckTriggered = false;
      if (mainWindow) {
        dialog.showMessageBox(mainWindow, {
          type: 'warning',
          buttons: ['OK'],
          title: 'Krexion Desktop',
          message: 'Could not check for updates.',
          detail:
            'Please check your internet connection and try again later.\n' +
            'You can keep using Krexion Desktop normally — the current ' +
            'version is fully functional.',
        }).catch(() => {});
      }
    }
  });
}

function checkForUpdatesAuto() {
  if (!app.isPackaged) {
    log.info('[updater] skipping: not packaged (dev mode)');
    return;
  }
  if (updateCheckInFlight) {
    log.info('[updater] skipping: check already in flight');
    return;
  }
  updateCheckInFlight = true;
  log.info(`[updater] kicking off update check (current v${app.getVersion()})`);
  autoUpdater.checkForUpdates().catch((err) => {
    updateCheckInFlight = false;
    log.error('[updater] checkForUpdates threw (suppressed)', err?.message || err);
  });
}

function checkForUpdatesManual() {
  if (!app.isPackaged) {
    if (mainWindow) {
      dialog.showMessageBox(mainWindow, {
        type: 'info',
        buttons: ['OK'],
        title: 'Krexion Desktop',
        message: 'Updates are only checked in installed builds.',
        detail: 'You are running an unpackaged developer build.',
      }).catch(() => {});
    }
    return;
  }
  manualCheckTriggered = true;
  checkForUpdatesAuto();
}

// ── IPC bridge for the in-app UpdateBanner ───────────────────────────────────
// 2026-06-11: The React UpdateBanner (shared with the cloud web app)
// previously POSTed to /api/system/install-update, which on Electron just
// writes a flag file that nothing on the desktop watches — so the customer's
// "Install update" click was a no-op. These two IPC channels let the
// renderer talk straight to electron-updater so a single click downloads
// (if needed) and installs the new build — no manual download / reinstall.
//
// Registered ONCE in the main process. The handlers swallow all errors so
// a malformed renderer call can never crash the app.
let updateIpcRegistered = false;
function registerUpdateIpc() {
  if (updateIpcRegistered) return;
  updateIpcRegistered = true;

  // Renderer asks "is there an update?" — used by the banner to refresh
  // its visible/hidden state without waiting for the next 6 h auto-cycle.
  ipcMain.handle('krexion:check-for-updates', async () => {
    if (!app.isPackaged) {
      return { ok: false, dev: true, version: app.getVersion() };
    }
    try {
      const r = await autoUpdater.checkForUpdates();
      const info = r && r.updateInfo ? r.updateInfo : null;
      return {
        ok: true,
        currentVersion: app.getVersion(),
        latestVersion: info ? info.version : null,
        updateAvailable: Boolean(info && info.version && info.version !== app.getVersion()),
      };
    } catch (err) {
      log.error('[ipc] check-for-updates failed', err);
      return { ok: false, error: String(err && err.message || err) };
    }
  });

  // Renderer asks "install the update now". electron-updater downloads
  // (idempotent — does nothing if already cached) and then runs
  // quitAndInstall which closes the app and launches the NSIS installer
  // silently. The customer sees a brief progress dialog and the app
  // restarts on the new version. No uninstall / reinstall by hand.
  ipcMain.handle('krexion:install-update', async () => {
    if (!app.isPackaged) {
      return { ok: false, dev: true, message: 'Dev build — no installer to swap.' };
    }
    try {
      // Make sure we have the latest manifest + binary cached.
      await autoUpdater.checkForUpdates().catch(() => {});
      await autoUpdater.downloadUpdate().catch(() => {});
      log.info('[ipc] customer clicked Install update — running quitAndInstall');
      isQuitting = true;
      // Defer slightly so the renderer can show a "Restarting…" state
      // before the window is destroyed.
      setTimeout(() => {
        try {
          autoUpdater.quitAndInstall(false, true);
        } catch (err) {
          log.error('[ipc] quitAndInstall threw', err);
        }
      }, 250);
      return { ok: true, restarting: true };
    } catch (err) {
      log.error('[ipc] install-update failed', err);
      return { ok: false, error: String(err && err.message || err) };
    }
  });

  log.info('[ipc] update bridge registered (krexion:check-for-updates, krexion:install-update)');
}

// ── Lifecycle ────────────────────────────────────────────────────────────────
// Install the `app://` protocol request handler. Runs once `app` is ready
// (otherwise `protocol.handle` throws). The handler resolves URLs like:
//
//   app://krexion/                  → resources/krexion/frontend/index.html
//   app://krexion/static/js/foo.js  → resources/krexion/frontend/static/js/foo.js
//   app://krexion/login             → resources/krexion/frontend/index.html  (SPA fallback)
//   app://krexion/dashboard         → resources/krexion/frontend/index.html  (SPA fallback)
//
// Any path that doesn't map to a real file inside `frontendDir` falls back
// to index.html so React's BrowserRouter can handle client-side routing for
// every route the user navigates to (including initial deep-links from a
// `app://krexion/some/route` direct load).
//
// Symlink / path-traversal hardening: we resolve the candidate file to its
// absolute path and refuse anything outside frontendDir. Otherwise a
// malicious URL like `app://krexion/../../../../Windows/System32/cmd.exe`
// could read arbitrary files from the customer's machine.
function registerAppProtocol() {
  const frontendDirReal = fs.realpathSync.native
    ? fs.realpathSync.native(frontendDir)
    : fs.realpathSync(frontendDir);

  protocol.handle('app', async (request) => {
    try {
      const url = new URL(request.url);
      // url.host = 'krexion', url.pathname starts with '/'.
      const rawPath = decodeURIComponent(url.pathname);
      // Strip a leading slash so path.join doesn't treat it as absolute.
      const relPath = rawPath.replace(/^[\\/]+/, '');

      let filePath = path.join(frontendDir, relPath);
      // Resolve symlinks etc. to a real on-disk path, then verify it's still
      // inside frontendDir. If not, force SPA fallback.
      let isFile = false;
      try {
        const real = fs.realpathSync.native
          ? fs.realpathSync.native(filePath)
          : fs.realpathSync(filePath);
        if (real.toLowerCase().startsWith(frontendDirReal.toLowerCase())) {
          const stat = fs.statSync(real);
          isFile = stat.isFile();
          filePath = real;
        }
      } catch {
        // not exist → falls through to index.html
      }
      if (!isFile) {
        filePath = path.join(frontendDir, 'index.html');
      }
      return net.fetch(pathToFileURL(filePath).toString());
    } catch (err) {
      log.error('[app://] handler error', err);
      // Last-resort fallback: try index.html.
      return net.fetch(pathToFileURL(path.join(frontendDir, 'index.html')).toString());
    }
  });
  log.info(`[app://] protocol handler registered, frontendDir=${frontendDir}`);
}

async function boot() {
  try {
    registerAppProtocol();
    createSplash();
    await startMongo();
    log.info('[boot] mongo ready');
    await startBackend();
    log.info('[boot] backend ready');
    // Diagnostic probe: confirm the backend really answers a real auth
    // endpoint (not just /api/ or /docs). Hitting /api/auth/login with a
    // bogus payload should return 401 within ~50 ms. Anything slower or
    // a non-2xx/4xx response is logged so support can spot pathological
    // states (mongo deadlock, blocking imports, etc.) from main.log.
    void backendHealthProbe();
    createMainWindow();
    createTray();
    // Configure auto-updater AFTER UI is up. We delay the actual network
    // check by ~3 s so a slow internet connection at startup never blocks
    // the customer from seeing the dashboard.
    configureAutoUpdater();
    registerUpdateIpc();
    setTimeout(checkForUpdatesAuto, 3000);
    // Re-check every 6 hours while the app stays open (matches Spotify /
    // VS Code update cadence). 6 h = 21_600_000 ms.
    setInterval(checkForUpdatesAuto, 6 * 60 * 60 * 1000);
  } catch (err) {
    log.error('[boot] failed', err);
    dialog.showErrorBox(
      'Krexion Desktop — startup failed',
      `${err.message || err}\n\nLogs: ${logsDir}`
    );
    isQuitting = true;
    app.quit();
  }
}

// Fire a couple of test requests at the freshly-started backend to surface
// latency / failure modes in main.log. Never throws — purely diagnostic.
async function backendHealthProbe() {
  const probes = [
    { name: 'GET /api/',           method: 'GET',  path: '/api/' },
    { name: 'POST /api/auth/login (probe)', method: 'POST', path: '/api/auth/login',
      body: JSON.stringify({ email: '__health_probe__@krexion.local', password: '__probe__' }) },
  ];
  for (const p of probes) {
    const started = Date.now();
    await new Promise((resolve) => {
      const req = http.request(
        {
          host: '127.0.0.1', port: BACKEND_PORT, path: p.path, method: p.method,
          headers: { 'Content-Type': 'application/json' },
          timeout: 10_000,
        },
        (res) => {
          let body = '';
          res.on('data', (c) => { body += c.toString(); if (body.length > 400) body = body.slice(0, 400); });
          res.on('end', () => {
            log.info(`[healthprobe] ${p.name} -> ${res.statusCode} in ${Date.now() - started} ms`);
            resolve();
          });
        }
      );
      req.on('error', (err) => {
        log.error(`[healthprobe] ${p.name} FAILED after ${Date.now() - started} ms: ${err.message}`);
        resolve();
      });
      req.on('timeout', () => {
        log.error(`[healthprobe] ${p.name} TIMED OUT after ${Date.now() - started} ms`);
        try { req.destroy(); } catch (_) {}
        resolve();
      });
      if (p.body) req.write(p.body);
      req.end();
    });
  }
}

app.on('ready', boot);

app.on('window-all-closed', (e) => {
  // Keep running in tray on Windows.
  if (process.platform !== 'darwin') e.preventDefault?.();
});

app.on('before-quit', () => {
  isQuitting = true;
  for (const p of [backendProc, mongoProc]) {
    if (p && !p.killed) {
      try { p.kill(); } catch (_) {}
    }
  }
});

process.on('uncaughtException', (err) => log.error('uncaughtException', err));
process.on('unhandledRejection', (err) => log.error('unhandledRejection', err));
