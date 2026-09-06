/* eslint-disable no-console */
// ─────────────────────────────────────────────────────────────────────────────
// prepare-resources.js
// ─────────────────────────────────────────────────────────────────────────────
// Populates electron-desktop/resources/krexion/** with everything the
// packaged app needs to run 100% locally on the customer's PC:
//
//   resources/krexion/
//     python/         — Embedded Python 3.11 (Windows x64) with deps installed
//     mongodb/        — Portable MongoDB Community Server (Windows x64)
//     backend/        — A copy of /app/backend (the FastAPI server)
//     frontend/       — The production React build (CRA `build/` output)
//     icon.ico        — Krexion icon (copied from installer/krexion.ico)
//
// Designed to run on the windows-latest GitHub Actions runner. Idempotent —
// existing downloads are reused. Never modifies the source repo.
// ─────────────────────────────────────────────────────────────────────────────

const fs = require('fs');
const path = require('path');
const https = require('https');
const { spawnSync, execSync } = require('child_process');

const ROOT = path.resolve(__dirname, '..');
const REPO = path.resolve(ROOT, '..');
const RES = path.join(ROOT, 'resources', 'krexion');
const CACHE = path.join(ROOT, '.cache');

fs.mkdirSync(RES, { recursive: true });
fs.mkdirSync(CACHE, { recursive: true });

const PYTHON_VERSION = '3.11.9';
const PYTHON_URL =
  `https://www.python.org/ftp/python/${PYTHON_VERSION}/python-${PYTHON_VERSION}-embed-amd64.zip`;
const PIP_BOOTSTRAP_URL = 'https://bootstrap.pypa.io/get-pip.py';

const MONGO_VERSION = '7.0.14';
const MONGO_URL =
  `https://fastdl.mongodb.org/windows/mongodb-windows-x86_64-${MONGO_VERSION}.zip`;

// ── Packages to EXCLUDE from the Electron bundle ─────────────────────────────
// These are Unix-only / Linux-only packages pulled in by backend/requirements.txt
// that either have NO Windows wheel OR fail to build from source on Windows.
// On the customer's Windows machine the backend (uvicorn) automatically falls
// back to the default asyncio loop (no `--loop uvloop` flag is used by the
// Electron launcher in src/main.js), so excluding these is functionally safe.
//
// Same approach as `build/build-backend.py` for the Inno-Setup native bundle —
// keeping the two excluder lists aligned avoids "works in native, fails in
// Electron" surprises.
//
// IMPORTANT: We do NOT modify backend/requirements.txt — VPS Linux deploy
// continues to install uvloop etc. as before. The exclusion only happens
// for the Electron Windows build via a filtered requirements file written
// to .cache/requirements-electron.txt.
const EXCLUDE_PACKAGES = new Set([
  'uvloop',         // libuv asyncio loop — no Windows support (THE root cause of run #4 failure)
  'daemonize',      // uses os.fork — Unix only
  'pexpect',        // pty/fcntl-based — Unix only
  'ptyprocess',     // transitive of pexpect — Unix only
  'pytun-pmd3',     // TUN/TAP networking — Unix only
  'sslpsk-pmd3',    // PSK SSL — C build issues on Windows
  'librt',          // Linux real-time POSIX library
  'plumbum',        // SSH/local exec — Windows half-broken, transitive only
].map((p) => p.toLowerCase().replace(/-/g, '_')));

function normalisePkgName(name) {
  return name.toLowerCase().replace(/-/g, '_');
}

// ── tiny helpers ─────────────────────────────────────────────────────────────
function log(msg) { console.log(`[prepare] ${msg}`); }
function run(cmd, args, opts = {}) {
  log(`$ ${cmd} ${args.join(' ')}`);
  const r = spawnSync(cmd, args, { stdio: 'inherit', shell: false, ...opts });
  if (r.status !== 0) throw new Error(`${cmd} failed with exit code ${r.status}`);
}
// Same as run() but returns the exit code instead of throwing — used for the
// per-package install fallback where we WANT to continue on individual failures.
function runStatus(cmd, args, opts = {}) {
  log(`$ ${cmd} ${args.join(' ')}`);
  const r = spawnSync(cmd, args, { stdio: 'inherit', shell: false, ...opts });
  return r.status === null ? 1 : r.status;
}

// ── Write a filtered requirements file ───────────────────────────────────────
// Reads backend/requirements.txt and writes .cache/requirements-electron.txt
// with EXCLUDE_PACKAGES removed. Returns the path to the filtered file.
function writeFilteredRequirements() {
  const src = path.join(REPO, 'backend', 'requirements.txt');
  const dst = path.join(CACHE, 'requirements-electron.txt');
  const raw = fs.readFileSync(src, 'utf8').split(/\r?\n/);
  const keep = [];
  const skipped = [];
  for (const rawLine of raw) {
    const line = rawLine.trim();
    if (!line || line.startsWith('#')) { keep.push(rawLine); continue; }
    // Parse package name — strip version / extras / markers
    const pkg = line.split('==')[0].split('>=')[0].split('<=')[0]
      .split('[')[0].split(';')[0].trim();
    if (EXCLUDE_PACKAGES.has(normalisePkgName(pkg))) {
      skipped.push(pkg);
    } else {
      keep.push(rawLine);
    }
  }
  fs.writeFileSync(dst, keep.join('\n') + '\n');
  log(`requirements: ${keep.length} keep, ${skipped.length} excluded → ${path.basename(dst)}`);
  for (const s of skipped) log(`   excluded (Unix-only): ${s}`);
  return dst;
}

// ── Install backend deps with bulk-then-per-package fallback ─────────────────
// Pass 1: bulk install of the filtered requirements file (fast path).
// Pass 2: if bulk fails, install per-line and skip individual failures — so a
//         single new transitive incompatibility doesn't tank the whole build.
function installBackendRequirements(pythonExe, reqFile) {
  const baseArgs = [
    '-m', 'pip', 'install',
    '--no-warn-script-location',
    '--prefer-binary',
    '--extra-index-url', 'https://d33sy5i8bnduwe.cloudfront.net/simple/',
  ];

  // Pass 1: bulk
  log('Pass 1: bulk install of filtered requirements');
  const bulkStatus = runStatus(pythonExe, [...baseArgs, '-r', reqFile]);
  if (bulkStatus === 0) {
    log('  bulk install OK');
    return;
  }
  log(`  bulk install returned exit ${bulkStatus} — falling back to per-package install`);

  // Pass 2: per-package
  const lines = fs.readFileSync(reqFile, 'utf8').split(/\r?\n/)
    .map((l) => l.trim()).filter((l) => l && !l.startsWith('#'));
  log(`Pass 2: installing ${lines.length} packages individually (skip-on-failure)`);
  let okCount = 0;
  const failed = [];
  for (const line of lines) {
    const pkg = line.split('==')[0].split('>=')[0].split('<=')[0]
      .split('[')[0].split(';')[0].trim();
    const status = runStatus(pythonExe, [...baseArgs, line]);
    if (status === 0) okCount += 1;
    else failed.push(pkg);
  }
  log(`Pass 2 done: ${okCount} installed, ${failed.length} skipped`);
  for (const p of failed) log(`   skipped: ${p}`);

  // Verify the CORE Krexion runtime imports — these MUST be present or the
  // packaged Electron app will crash on first launch.
  const core = [
    'fastapi', 'uvicorn', 'starlette', 'pydantic', 'pydantic_core',
    'motor', 'pymongo', 'bcrypt', 'cryptography', 'httpx',
    'passlib', 'jose', 'playwright',
  ];
  log(`Verifying core packages importable: ${core.join(', ')}`);
  const code = core.map((p) => `import ${p}`).join('; ');
  const verifyStatus = runStatus(pythonExe, ['-c', code]);
  if (verifyStatus !== 0) {
    throw new Error(
      `Core backend package import failed after install. ` +
      `Skipped packages: ${failed.join(', ') || '(none)'}`
    );
  }
  log('  all core packages OK');
}

function download(url, dest) {
  if (fs.existsSync(dest) && fs.statSync(dest).size > 0) {
    log(`cached: ${path.basename(dest)}`);
    return Promise.resolve();
  }
  log(`download: ${url}`);
  return new Promise((resolve, reject) => {
    const file = fs.createWriteStream(dest + '.part');
    const get = (u) => {
      https.get(u, { headers: { 'user-agent': 'krexion-desktop-build' } }, (res) => {
        if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
          res.resume();
          return get(res.headers.location);
        }
        if (res.statusCode !== 200) {
          return reject(new Error(`HTTP ${res.statusCode} for ${u}`));
        }
        res.pipe(file);
        file.on('finish', () => file.close(() => {
          fs.renameSync(dest + '.part', dest);
          resolve();
        }));
      }).on('error', reject);
    };
    get(url);
  });
}

function unzip(zipPath, destDir) {
  fs.mkdirSync(destDir, { recursive: true });
  if (process.platform === 'win32') {
    run('powershell', [
      '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command',
      `Expand-Archive -Force -LiteralPath '${zipPath}' -DestinationPath '${destDir}'`
    ]);
  } else {
    run('unzip', ['-o', '-q', zipPath, '-d', destDir]);
  }
}

function rimraf(p) {
  if (fs.existsSync(p)) fs.rmSync(p, { recursive: true, force: true });
}

function copyDir(src, dest, filter = () => true) {
  fs.mkdirSync(dest, { recursive: true });
  for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
    const s = path.join(src, entry.name);
    const d = path.join(dest, entry.name);
    if (!filter(s, entry)) continue;
    if (entry.isDirectory()) copyDir(s, d, filter);
    else if (entry.isFile()) fs.copyFileSync(s, d);
  }
}

// ── 1. Embedded Python ───────────────────────────────────────────────────────
async function preparePython() {
  const pyDir = path.join(RES, 'python');
  if (fs.existsSync(path.join(pyDir, 'python.exe'))) {
    log('python: already prepared');
    return;
  }
  rimraf(pyDir);
  const zip = path.join(CACHE, `python-${PYTHON_VERSION}-embed.zip`);
  await download(PYTHON_URL, zip);
  unzip(zip, pyDir);

  // Enable site-packages in the embedded distribution.
  const pth = fs.readdirSync(pyDir).find((f) => /^python\d+\._pth$/i.test(f));
  if (pth) {
    const full = path.join(pyDir, pth);
    let text = fs.readFileSync(full, 'utf8');
    if (text.includes('#import site')) text = text.replace('#import site', 'import site');
    if (!/\bLib\\site-packages\b/.test(text)) text += '\nLib\\site-packages\n';
    fs.writeFileSync(full, text);
  }

  // Install pip into the embedded python.
  const getPip = path.join(CACHE, 'get-pip.py');
  await download(PIP_BOOTSTRAP_URL, getPip);
  if (process.platform === 'win32') {
    run(path.join(pyDir, 'python.exe'), [getPip, '--no-warn-script-location']);
    // Install backend requirements via the FILTERED list (.cache/
    // requirements-electron.txt) so Unix-only packages like uvloop don't
    // abort the entire install. Uses a robust 2-pass strategy:
    //   Pass 1: bulk install of the filtered file.
    //   Pass 2: if bulk fails, install per-package and skip individual
    //           failures, then verify CORE imports (fastapi, uvicorn,
    //           motor, pymongo, pydantic, etc.) succeed.
    // The backend pins `emergentintegrations==0.1.0`, which lives on
    // Emergent's private index (not on PyPI). We add that index as an
    // `--extra-index-url` so pip can resolve it while still pulling the
    // rest from PyPI.
    const reqFiltered = writeFilteredRequirements();
    installBackendRequirements(path.join(pyDir, 'python.exe'), reqFiltered);
  } else {
    log('python: non-Windows host — skipping pip install (resources will be incomplete).');
  }
}

// ── 2. Portable MongoDB ──────────────────────────────────────────────────────
async function prepareMongo() {
  const mongoDir = path.join(RES, 'mongodb');
  if (fs.existsSync(path.join(mongoDir, 'bin', 'mongod.exe'))) {
    log('mongodb: already prepared');
    return;
  }
  rimraf(mongoDir);
  const zip = path.join(CACHE, `mongodb-${MONGO_VERSION}.zip`);
  await download(MONGO_URL, zip);
  const tmp = path.join(CACHE, `mongo-extract-${MONGO_VERSION}`);
  rimraf(tmp);
  unzip(zip, tmp);
  // The archive extracts to a single mongodb-windows-* folder. Flatten it.
  const inner = fs.readdirSync(tmp).find((n) => n.toLowerCase().startsWith('mongodb-'));
  if (!inner) throw new Error('mongo: unexpected archive layout');
  fs.renameSync(path.join(tmp, inner), mongoDir);
  rimraf(tmp);

  // ── Trim MongoDB to just what we actually need ───────────────────────────
  // The MongoDB Community 7.0.14 Windows zip contains a bunch of binaries
  // and debug symbols that Krexion Desktop never uses:
  //
  //   bin/mongos.exe          — cluster routing (we run a single mongod)
  //   bin/mongod.pdb          — debug symbols for mongod (~400 MB!)
  //   bin/mongos.pdb          — debug symbols for mongos (~400 MB!)
  //   bin/install_compass.ps1 — installer for the optional Compass GUI
  //
  // Removing these saves ~700 MB+ of disk space, which directly reduces
  // both the installer size AND the temporary space the NSIS installer
  // needs to extract into %TEMP% on the customer's machine. The actual
  // mongod.exe (the database daemon Krexion uses) is left untouched.
  //
  // Anything we can't find (e.g. MongoDB changed its packaging) is skipped
  // silently — defensive code so a future MongoDB release doesn't break
  // the Electron build.
  const trimTargets = [
    'mongos.exe',
    'mongod.pdb',
    'mongos.pdb',
    'install_compass.ps1',
  ];
  const binDir = path.join(mongoDir, 'bin');
  let bytesFreed = 0;
  for (const fname of trimTargets) {
    const fpath = path.join(binDir, fname);
    if (fs.existsSync(fpath)) {
      const sz = fs.statSync(fpath).size;
      try {
        fs.unlinkSync(fpath);
        bytesFreed += sz;
        log(`mongodb: removed ${fname} (${(sz / 1024 / 1024).toFixed(1)} MB)`);
      } catch (err) {
        log(`mongodb: WARNING failed to remove ${fname}: ${err.message}`);
      }
    }
  }
  log(`mongodb: trim freed ${(bytesFreed / 1024 / 1024).toFixed(1)} MB`);

  // Sanity check — make sure mongod.exe is still there. If the trim went
  // sideways and somehow deleted the daemon, fail loudly NOW (during
  // build) rather than later when the customer's installed app fails to
  // start with a confusing "ENOENT mongod.exe".
  if (!fs.existsSync(path.join(binDir, 'mongod.exe'))) {
    throw new Error('mongodb: mongod.exe missing after trim — refusing to package broken build');
  }
}

// ── 3. Backend snapshot ──────────────────────────────────────────────────────
function prepareBackend() {
  const dest = path.join(RES, 'backend');
  rimraf(dest);
  const src = path.join(REPO, 'backend');
  copyDir(src, dest, (full, entry) => {
    const rel = path.relative(src, full);
    if (entry.isDirectory()) {
      if (['__pycache__', 'tests', 'form_filler_results',
           'real_user_traffic_results', 'visual_recorder_sessions',
           'uploaded_resources'].includes(entry.name)) return false;
    }
    if (entry.isFile()) {
      if (entry.name.endsWith('.pyc')) return false;
      if (entry.name === '.env') return false; // never bundle dev .env
    }
    return true;
  });
  // Write a minimal .env so the backend has sane defaults even before the
  // installer drops a real one in %PROGRAMDATA%\Krexion-Desktop.
  //
  // 2026-02 — v2.1.13: KREXION_MODE=native flips the React shell into the
  // AdsPower-style sidebar/topbar (NativeShell.js). Electron main.js also
  // sets this in the spawn env, but we mirror it here so a customer who
  // launches uvicorn manually (e.g. KREXION-LOGS.bat) still gets the
  // native UI.
  //
  // 2026-02 — v2.1.15: KREXION_CLOUD_URL points the in-app cloud proxy
  // at the public krexion.com edge. /api/auth/*, /api/admin/*,
  // /api/license/* and /api/links/* are forwarded there; everything
  // else (clicks, RUT, conversions, settings, automation) stays local.
  // See backend/cloud_proxy_module.py for the full design.
  const envFile = path.join(dest, '.env');
  fs.writeFileSync(envFile,
    'MONGO_URL=mongodb://127.0.0.1:27117\n' +
    'DB_NAME=krexion_local\n' +
    'KREXION_MODE=native\n' +
    'KREXION_DESKTOP=1\n' +
    'KREXION_CLOUD_URL=https://krexion.com\n'
  );
  log('backend: copied');
}

// ── 4. Frontend build ────────────────────────────────────────────────────────
function prepareFrontend() {
  const dest = path.join(RES, 'frontend');
  rimraf(dest);
  const frontDir = path.join(REPO, 'frontend');

  // Build with REACT_APP_BACKEND_URL pinned to the local backend so the
  // packaged app never talks to the cloud for app data.
  //
  // REACT_APP_DESKTOP_BUILD=1 flips the React app into "desktop mode":
  //   * the marketing HomePage at "/" is bypassed and the customer lands
  //     directly on the login form;
  //   * LoginPage hides the cloud-marketing left panel and shows a
  //     "Buy License" link that opens krexion.com/pricing in the user's
  //     default browser.
  // The flag is read once at build time (Create-React-App inlines it).
  // Cloud builds never set this var, so their behavior is unchanged.
  const env = {
    ...process.env,
    REACT_APP_BACKEND_URL: 'http://127.0.0.1:8088',
    REACT_APP_DESKTOP_BUILD: '1',
    CI: 'false',
    GENERATE_SOURCEMAP: 'false',
    INLINE_RUNTIME_CHUNK: 'false',
    PUBLIC_URL: '.', // produce relative asset URLs so file:// loading works
  };
  log('frontend: yarn install');
  run('yarn', ['install', '--network-timeout', '600000'], { cwd: frontDir, env, shell: true });
  // Cross-platform craco build.
  //
  // frontend/package.json's "build" script uses the Unix-shell-only
  // syntax `CI=false craco build`, which Windows cmd / PowerShell
  // can't parse and dies with `'CI' is not recognized as an internal
  // or external command`. We don't want to touch frontend/package.json
  // (any change there would also flow through to the VPS deploy
  // pipeline). Instead, we set CI=false via the spawn `env` above and
  // invoke craco DIRECTLY via npx, bypassing the broken yarn script.
  log('frontend: npx craco build (bypass package.json script for Windows)');
  run('npx', ['--no-install', 'craco', 'build'], { cwd: frontDir, env, shell: true });

  const built = path.join(frontDir, 'build');
  if (!fs.existsSync(built)) throw new Error('frontend: build/ not produced');
  copyDir(built, dest);
  log('frontend: copied build/ → resources/krexion/frontend');
}

// ── 4.5 Playwright Chromium ──────────────────────────────────────────────────
// 2026-06-11 (v2.1.40): Browser-Profile launch (and Real-User-Traffic, and
// every heavy automation feature) requires a real Chromium binary at
// runtime. Earlier Electron builds installed the Playwright Python package
// but never ran `playwright install`, so the bundled app shipped with no
// browser — on first launch the backend logged
//   "Playwright chromium-headless-shell rev XXX missing"
// and any feature that opens a profile failed silently.
//
// We mirror exactly what `.github/workflows/build-windows-release.yml`
// does for the Inno-Setup native installer: invoke Playwright's CLI on the
// build runner to download Chromium into a folder we then ship as part of
// `resources/krexion/`. Backend (main.js → startBackend) sets
// PLAYWRIGHT_BROWSERS_PATH to that folder so the browser is found offline.
//
// We ship BOTH `chromium` (full, used by headed Browser-Profile sessions)
// and `chromium-headless-shell` (smaller, used by RUT / automation). The
// runtime picks one based on the job kind. Yes this adds ~300 MB to the
// installer, but the alternative is a feature that silently does nothing.
function prepareChromium() {
  const dest = path.join(RES, 'chromium');
  if (fs.existsSync(dest)) {
    const existing = fs.readdirSync(dest).filter((n) => n.startsWith('chromium'));
    if (existing.length > 0) {
      log(`chromium: cached (${existing.length} build(s) under ${dest}) — skipping`);
      return;
    }
  }
  fs.mkdirSync(dest, { recursive: true });

  const pythonExe = path.join(RES, 'python', 'python.exe');
  if (!fs.existsSync(pythonExe)) {
    throw new Error('chromium: embedded python not found — preparePython() must run first');
  }
  const env = {
    ...process.env,
    PLAYWRIGHT_BROWSERS_PATH: dest,
    PYTHONHOME: path.join(RES, 'python'),
    PYTHONPATH: path.join(RES, 'python', 'Lib', 'site-packages'),
    PYTHONIOENCODING: 'utf-8',
    PYTHONUTF8: '1',
  };
  log('chromium: downloading via playwright install (this can take 5-10 min)');
  // Don't throw on non-zero — Playwright sometimes reports rc=1 even when
  // browsers are fully extracted. We verify by checking the dest folder.
  const r = spawnSync(
    pythonExe,
    ['-m', 'playwright', 'install', 'chromium', 'chromium-headless-shell'],
    { stdio: 'inherit', shell: false, env }
  );
  if (r.status !== 0) {
    log(`chromium: playwright install exited rc=${r.status} — verifying folder before failing`);
  }
  const installed = fs.existsSync(dest)
    ? fs.readdirSync(dest).filter((n) => n.startsWith('chromium'))
    : [];
  if (installed.length === 0) {
    throw new Error('chromium: playwright install produced no browser folder under ' + dest);
  }
  log(`chromium: ready (${installed.join(', ')}) under ${dest}`);
}

// ── 5. Icon ──────────────────────────────────────────────────────────────────

// ── 4.6 Krexion Kernel (Cloak C++ Chromium — AdsPower-class) ─────────────────
// v2.9.0: headed Browser Profiles require Cloak C++ Chromium. Bundle it under
// resources/krexion/krexion-kernel/ so Open Profile never falls back to stock
// Playwright Chromium on customer PCs.
function prepareKrexionKernel() {
  const dest = path.join(RES, 'krexion-kernel');
  const chromeExe = path.join(dest, process.platform === 'win32' ? 'chrome.exe' : 'chrome');
  if (fs.existsSync(chromeExe)) {
    log(`krexion-kernel: cached (${chromeExe}) — skipping`);
    return;
  }
  fs.mkdirSync(dest, { recursive: true });
  const pythonExe = path.join(RES, 'python', process.platform === 'win32' ? 'python.exe' : 'python');
  const script = path.join(REPO, 'backend', 'scripts', 'bundle_krexion_kernel.py');
  if (!fs.existsSync(script)) {
    throw new Error('krexion-kernel: bundle_krexion_kernel.py missing at ' + script);
  }
  // Ensure cloakbrowser is present in embedded python (requirements already include it).
  const env = { ...process.env, PYTHONIOENCODING: 'utf-8', PYTHONUTF8: '1' };
  log('krexion-kernel: bundling Cloak C++ Chromium (AdsPower-class)');
  const platformArg = process.platform === 'win32' ? 'windows-x64' : 'native';
  let r = spawnSync(
    pythonExe,
    [script, '--dest', dest, '--platform', platformArg],
    { stdio: 'inherit', shell: false, env }
  );
  if ((r.status !== 0 || !fs.existsSync(chromeExe)) && fs.existsSync(pythonExe)) {
    // Fallback: pip install cloakbrowser then retry native ensure
    spawnSync(pythonExe, ['-m', 'pip', 'install', '-q', 'cloakbrowser>=0.5.0'], {
      stdio: 'inherit', shell: false, env,
    });
    r = spawnSync(
      pythonExe,
      [script, '--dest', dest, '--platform', platformArg],
      { stdio: 'inherit', shell: false, env }
    );
  }
  if (!fs.existsSync(chromeExe)) {
    throw new Error('krexion-kernel: Cloak C++ chrome binary missing after bundle at ' + chromeExe);
  }
  log(`krexion-kernel: ready at ${chromeExe}`);
}

function prepareIcon() {
  const src = path.join(REPO, 'installer', 'krexion.ico');
  const dest = path.join(RES, 'icon.ico');
  if (fs.existsSync(src)) {
    fs.copyFileSync(src, dest);
    fs.copyFileSync(src, path.join(ROOT, 'build', 'icon.ico'));
    log('icon: copied');
  } else {
    log('icon: krexion.ico not found, electron-builder will use default');
  }
}

// ── main ─────────────────────────────────────────────────────────────────────
(async () => {
  fs.mkdirSync(path.join(ROOT, 'build'), { recursive: true });
  await preparePython();
  await prepareMongo();
  prepareBackend();
  prepareFrontend();
  prepareChromium();
  prepareKrexionKernel();
  prepareIcon();
  log('✅ resources ready at ' + RES);
})().catch((err) => {
  console.error('[prepare] FAILED:', err);
  process.exit(1);
});
