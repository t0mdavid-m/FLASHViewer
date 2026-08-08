# FLASHApp Desktop

Packages FLASHApp as a self-contained desktop app for Windows, macOS and Linux.
Electron spawns a bundled Python running Streamlit on a random localhost port and
loads it in a window. End users install nothing — no Python, no Node, no browser
setup.

```bash
cd desktop
./build.sh              # stage repo + portable Python + deps + TOPP tools
npm install
npm start               # dev run
npx electron-builder    # .dmg / .exe / .AppImage for the host OS
```

Installers must be built on their target OS and architecture — there is no
cross-compiling, because each build downloads a portable CPython for its own
platform. `.github/workflows/desktop.yml` covers four targets:

| Target | Runner | Output |
|---|---|---|
| macOS arm64 | `macos-14` | `.dmg` |
| Linux x64 | `ubuntu-24.04` | `.AppImage` |
| Linux arm64 | `ubuntu-24.04-arm` | `.AppImage` |
| Windows x64 | `windows-2022` | `.exe` |

Intel macOS is not built: those runners queue for hours, and Apple Silicon Macs
run the arm64 build natively while Intel Macs can run it under Rosetta.

Pushing a `desktop-v*` tag runs the same matrix and collects every installer into
a **draft** GitHub release, which you then review and publish by hand.

## How it works

`main.js` picks a free port, spawns `runtime/bin/python3 -m streamlit run app.py`,
waits for the port to answer, then opens a `BrowserWindow` on it. Nothing in
`app.py`, `src/` or `content/` had to change.

Two details worth knowing:

- The app writes workspaces to `../workspaces-FLASHViewer` relative to its cwd,
  which cannot be inside the read-only resource dir. `main.js` copies the payload
  into the per-user `userData` directory on first run and runs it from there.
- TOPP binaries staged into `topp/` are prepended to the child's `PATH`, which is
  how `CommandExecutor` resolves `FLASHDeconv` and friends. Without them the
  Viewer and Upload pages work and the Workflow pages do not. `build.sh` copies
  whatever it finds in `$OPENMS_BIN`.

## Pins (`constraints.txt`)

- `pyopenms==3.4.0` on macOS only — the 3.5.0 macOS wheels ship both
  `libomp.dylib` and `libgomp.1.dylib`, and importing pyopenms aborts with
  `OMP: Error #15`. The pin carries a `sys_platform == "darwin"` marker because
  3.4.0 has no linux-aarch64 wheel; Linux and Windows get 3.5.0.

Streamlit is no longer pinned. It was held at 1.42.2 because `captcha_.py`
imported four private `streamlit.source_util` symbols removed in 1.43 — but
nothing called the functions that used them, so deleting 167 lines of dead code
lifted the ceiling. The app is verified running on 1.60, which matters beyond
housekeeping: `st.navigation(position="top")` landed in 1.46, so a top header
bar is now a native primitive rather than CSS injection against Streamlit's
internals.

## Captcha

Off outside a public deployment. `captcha_control()` returns immediately unless
`settings.json` sets `online_deployment: true`, so desktop and local installs
never see it. This was previously true only as a side effect of `page_setup()`
presetting `controllo`; it is now explicit.

## Signing

Signing happens in CI only. No key is ever stored in the repo or on the runner.
Both platforms are wired up and stay dormant until the secrets exist — without
them the workflow still produces working unsigned installers.

### macOS — Apple Developer ID

Five repository secrets, all consumed directly by electron-builder:

| Secret | What |
|---|---|
| `MACOS_CERTIFICATE_BASE64` | Developer ID Application cert+key, `.p12` export, base64 |
| `MACOS_CERTIFICATE_PASSWORD` | password of that `.p12` |
| `MACOS_APPLE_ID` | Apple ID used for notarization |
| `MACOS_TEAM_ID` | Apple Developer Team ID |
| `MACOS_NOTARY_PASSWORD` | app-specific password for `notarytool` |

electron-builder does the keychain dance, `codesign`, `notarytool submit` and
stapling itself; the workflow only sets the environment and adds
`--config.mac.notarize=true`.

`resources/entitlements.mac.plist` is the part specific to shipping an interpreter.
Hardened runtime otherwise refuses to load `pyopenms`, `numpy` and `pyarrow`,
which are signed by their own publishers rather than by us, and refuses CPython's
writable-executable pages. Dropping `disable-library-validation` in particular
will produce an app that passes notarization and then crashes on first import.

Verify a build with:

```bash
codesign --verify --deep --strict --verbose=2 dist/mac-arm64/FLASHApp.app
spctl -a -vv dist/mac-arm64/FLASHApp.app
```

### Windows — SignPath Foundation

Two repository secrets, `SIGNPATH_API_TOKEN` and `SIGNPATH_ORG_ID`. The private
key stays in SignPath's HSM; there is no `.pfx` anywhere and nothing to back up.

This needs the project registered in a SignPath organization first — the workflow
assumes project slug `flashapp`, artifact configuration `initial`, signing policy
`release-signing`. Two things to get right in the console:

- The artifact configuration must expect a **ZIP**, because `upload-artifact`
  always zips. A bare `<pe-file>` fails with *"file does not correspond to the
  specified file type"*:
  ```xml
  <artifact-configuration xmlns="http://signpath.io/artifact-configuration/v1">
    <zip-file><pe-file path="*.exe"><authenticode-sign /></pe-file></zip-file>
  </artifact-configuration>
  ```
- The release policy requires a human to approve each request in SignPath →
  Signing Requests. `wait-for-completion: true` means the job blocks until someone
  clicks Approve, so be at the keyboard for a real release.

Validate the pipeline with the `test-signing` policy first. Test-cert signatures
chain to a non-public root and are *not* Windows-trusted — they prove the
pipeline works, not that the binary is shippable.

### Local builds

Unsigned, deliberately:

```bash
CSC_IDENTITY_AUTO_DISCOVERY=false npx electron-builder
```

## Not done yet

Auto-update.

## Why not stlite/WASM

stlite runs Python under Pyodide, which can only install pure-Python or
Emscripten-built wheels. FLASHApp needs three things Pyodide has no answer for:
`pyopenms` (compiled C++, no `wasm32` wheel exists), `subprocess` calls to native
TOPP tools, and the Vue custom component served from `js-component/dist`.
