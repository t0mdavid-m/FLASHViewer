const { app, BrowserWindow, shell, dialog } = require('electron')
const { spawn } = require('child_process')
const path = require('path')
const fs = require('fs')
const net = require('net')
const http = require('http')

const RES = app.isPackaged ? process.resourcesPath : __dirname
const WIN = process.platform === 'win32'
const PY = WIN ? path.join(RES, 'runtime', 'python.exe') : path.join(RES, 'runtime', 'bin', 'python3')
const ENTRY = process.env.STREAMLIT_ENTRY || 'app.py'

// Native file dialogs have to come from Electron. The app used tkinter, but on
// macOS Tk aborts the whole process when constructed off the main thread
// ("NSException", libc++abi terminate), and Streamlit runs page code in a
// ScriptRunner thread — so every dialog killed the Python process instead of
// opening. Electron owns the main thread, so it opens the dialog and the page
// asks over localhost.
function startDialogServer (token) {
  return new Promise(resolve => {
    const server = http.createServer(async (req, res) => {
      const url = new URL(req.url, 'http://127.0.0.1')
      const reply = (code, body) => {
        res.writeHead(code, { 'Content-Type': 'application/json' })
        res.end(JSON.stringify(body))
      }
      // Any local process could otherwise pop dialogs at the user.
      if (url.searchParams.get('token') !== token) return reply(403, { error: 'forbidden' })
      if (url.pathname !== '/pick') return reply(404, { error: 'not found' })

      const exts = (url.searchParams.get('types') || '').split(',').filter(Boolean)
      const directory = url.searchParams.get('directory') === '1'
      const win = BrowserWindow.getAllWindows()[0]
      const opts = {
        title: url.searchParams.get('title') || 'Select files',
        properties: directory
          ? ['openDirectory']
          : ['openFile', 'multiSelections']
      }
      if (!directory && exts.length) opts.filters = [{ name: exts.join('/'), extensions: exts }]

      try {
        const r = win ? await dialog.showOpenDialog(win, opts) : await dialog.showOpenDialog(opts)
        reply(200, { paths: r.canceled ? [] : r.filePaths })
      } catch (e) {
        reply(500, { error: String(e) })
      }
    })
    server.listen(0, '127.0.0.1', () => resolve(server.address().port))
  })
}

let py = null

// The app writes workspaces to ../workspaces-* relative to its cwd, so it cannot run
// from the read-only resource dir. Copy it into userData on first run / version bump.
function stageApp () {
  const dst = path.join(app.getPath('userData'), 'app')
  if (!app.isPackaged) return path.join(RES, 'app')
  const stamp = path.join(app.getPath('userData'), '.staged-version')
  const cur = fs.existsSync(stamp) ? fs.readFileSync(stamp, 'utf8') : ''
  if (cur !== app.getVersion()) {
    fs.rmSync(dst, { recursive: true, force: true })
    fs.cpSync(path.join(RES, 'app'), dst, { recursive: true })
    fs.writeFileSync(stamp, app.getVersion())
  }
  return dst
}

const freePort = () => new Promise(res => {
  const s = net.createServer()
  s.listen(0, '127.0.0.1', () => { const p = s.address().port; s.close(() => res(p)) })
})

const waitFor = (url, tries = 900) => new Promise((res, rej) => {
  const tick = () => http.get(url, r => { r.resume(); res() })
    .on('error', () => tries-- > 0 ? setTimeout(tick, 100) : rej(new Error('server did not start')))
  tick()
})

async function start () {
  const cwd = stageApp()
  const port = await freePort()
  const url = `http://127.0.0.1:${port}`
  const dialogToken = require('crypto').randomBytes(16).toString('hex')
  const dialogPort = await startDialogServer(dialogToken)

  py = spawn(PY, ['-m', 'streamlit', 'run', ENTRY,
    '--server.port', String(port),
    '--server.address', '127.0.0.1',
    '--server.headless', 'true',
    '--server.fileWatcherType', 'none',
    '--browser.gatherUsageStats', 'false',
    // Desktop references files in place rather than uploading them, but the
    // websocket still carries whole result frames to the viewer, and MS data is
    // routinely gigabytes. Streamlit's 200 MB defaults are a browser-era limit
    // that makes no sense for a local app.
    '--server.maxUploadSize', '1000000',
    '--server.maxMessageSize', '1000000'
  ], {
    cwd,
    // TOPP tools (FLASHDeconv, ...) are looked up on PATH by the app's CommandExecutor.
    // OPENMS_DATA_PATH from a developer shell would override our bundled share dir.
    env: {
      ...process.env,
      OPENMS_DATA_PATH: undefined,
      FLASHAPP_DESKTOP: '1',
      FLASHAPP_DIALOG_PORT: String(dialogPort),
      FLASHAPP_DIALOG_TOKEN: dialogToken,
      PATH: path.join(RES, 'topp') + path.delimiter + process.env.PATH
    }
  })

  let log = ''
  const keep = d => { log = (log + d).slice(-4000) }
  py.stdout.on('data', keep)
  py.stderr.on('data', keep)

  try {
    await waitFor(url)
  } catch (e) {
    dialog.showErrorBox('Failed to start', log || String(e))
    return app.quit()
  }

  const win = new BrowserWindow({ width: 1500, height: 950, title: app.getName() })
  win.loadURL(url)
  win.webContents.setWindowOpenHandler(({ url }) => { shell.openExternal(url); return { action: 'deny' } })
}

app.whenReady().then(start)
app.on('window-all-closed', () => app.quit())
app.on('quit', () => py && py.kill())
