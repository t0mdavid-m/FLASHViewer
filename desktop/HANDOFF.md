# FLASHApp desktop branch — handoff

Everything found, fixed, deferred or rejected while turning FLASHViewer into a
cross-platform desktop app and cleaning up what that exposed.

Branch `desktop` on `okohlbacher/FLASHViewer`, forked from `t0mdavid-m/FLASHViewer`
at `develop`. Draft PR: t0mdavid-m/FLASHViewer#90.

Test suite: `tests/run_all.sh` — 17 files. Each skips cleanly rather than passing
falsely when a prerequisite (example data, a FLASHDeconv binary) is absent.

---

## 1. Bugs in the app as it shipped

These were all present on `develop` before any of this work. Several are data-loss
or "workspace permanently broken" class. **They are the most valuable part of this
branch to upstream, independently of the desktop app.**

| # | Bug | Effect | Status |
|---|---|---|---|
| 1 | `Delete Workspace` joined an unsanitised text box into a path and `rmtree`'d it | Typing an absolute path deleted **that directory**; `..` removed every workspace | fixed, `valid_workspace_name()` + test |
| 2 | `store_file()` read `file.suffix` before its file-like branch; `UploadedFile` has no `.suffix` | **Every browser upload** raised `AttributeError` — the only path all three upload pages use | fixed |
| 3 | Dataset ids (user filenames) interpolated into SQL | One apostrophe made every later query raise `OperationalError`; the dataset stayed listed, its page threw, and it could not be deleted from inside the app | fixed, parameterised + identifier allow-list + test |
| 4 | Every file dialog used Tk off the main thread | On macOS this **aborts the process** (`NSException`, `libc++abi`), it does not raise. Streamlit runs page code in a ScriptRunner thread | fixed, Electron dialog over a token-guarded loopback endpoint |
| 5 | `clean-up-workspaces.py` looked in `/workspaces-flashapp`; the app writes `../workspaces-FLASHViewer` | The hosted janitor reclaimed **nothing**; abandoned workspaces accumulated forever | fixed |
| 6 | `export_parameters_markdown()` indexed an empty list when no TOPP ini files exist | Took down the whole Configure tab in any build without TOPP binaries | fixed |
| 7 | FLASHTnT "Add results" indexed `results['tags_tsv']` directly | Bare `KeyError` for anyone who added the two mzMLs before the TSVs | fixed, reports missing files and skips that dataset |
| 8 | `captcha_.py` imported four private `streamlit.source_util` symbols | Pinned Streamlit to 1.42.2 — **via dead code**; nothing called the functions using them | fixed, 167 lines deleted, unpinned, verified on 1.60 |

### Still open, deliberately

| Bug | Why not fixed |
|---|---|
| `src/masstable.py` assigns `df['CombinedPeaks'] = noisyPeaks`, duplicating `NoisyPeaks` | Visibly wrong, but it changes **plotted scientific data**. Needs a maintainer to state the intended semantics — guessing would be worse than the bug |
| `get_results_list()` silently drops columns that do not exist, degrading AND to partial | The root cause of #7 and a landmine for any "do I have this data?" check. `presets.py` already documents and avoids it. A real fix changes query semantics app-wide |
| `preset_page._cache_dir()` raises `KeyError` for `"FLASHQuant"`, plus three more FLASHQuant `KeyError`s in that module | Unreachable today (only the two Layout Manager pages call it). Becomes reachable the moment anything iterates all three tools |
| The Download zip is cached as `download_archive` and never invalidated | A re-run of the same dataset id serves a stale archive |
| A killed app leaves `pids/` behind, so the app believes a run is still executing | Pre-existing; the Run step status inherits it |
| ~~Destructive actions have no confirmation~~ | Fixed: typed confirmation for `Remove all`, a listing dialog for `Remove selected` |
| **FLASHQuant's two ingest routes derive different dataset ids** | The example-data button strips the glob `.fq.tsv` → `example`; the picker and uploader strip the role suffix `.tsv` → `example.fq`. Loading the examples and adding the same files by hand yields **two datasets for one experiment**. FLASHDeconv and FLASHTnT agree on both routes. Not normalised: the id is the join key existing workspaces are keyed on, so changing either route orphans data already in a cache. Needs a decision on which is canonical |
| The paste-a-path box fired on text presence | Fixed: it is now an explicit "Add from path" button. A keyed `text_input` keeps its value across reruns, so the old form re-ingested every rerun and raced the caller's `st.rerun()` |
| `src/fileupload.py` (all five functions) and `content/TODO_Update/*` are dead | Unreferenced; deleting them belongs in its own change |

---

## 2. Bugs introduced during this work, and caught

Recorded because the pattern matters more than the individual mistakes: **every one
was caught by an adversarial review or a test, not by the change's author.**

| Bug | How it would have failed | Caught by |
|---|---|---|
| `link=` inferred from "is this a Path on desktop" | Linked the workflow's **own temp output**, which is deleted seconds later — every desktop run would have produced an unopenable dataset | design review |
| Making `link` default to `False` then sent the desktop picker down the copy branch, where `remove=True` unlinks the source | **Deleted the user's original mzML** on add. Reproduced before and after | adversarial review of the design |
| Removing the uploader left `files_dir` empty, so the "no data yet" branch always won and referenced files were never listed | Picking a file appeared to do nothing | user report |
| Phase 1 deleted the layout editor that owned the comparison slot count | Multi-dataset comparison became unreachable | self-review before commit |
| Tab flattening | `IndexError` at runtime | smoke test |
| An emoji-removal regex collapsed whitespace runs | Destroyed indentation in ten files | next `git diff` |
| `test_input_listing.py` re-implemented the logic it was testing | Would have stayed green through a refactor that broke the real code | adversarial review of the plan |

**Lesson worth keeping:** ownership must be a recorded property of a file, never
inferred from deployment mode or argument type. Both data-loss bugs above are the
same mistake in two forms.

---

## 3. The desktop app

Electron spawns a bundled portable Python running Streamlit on a random localhost
port. `desktop/` plus one CI workflow; nothing outside it is desktop-specific except
the `FLASHAPP_DESKTOP` branches.

Decisions and the reasons, so they are not relitigated:

- **stlite/WASM is impossible here.** Pyodide installs only pure-Python or
  Emscripten wheels; FLASHApp needs `pyopenms` (compiled C++, no `wasm32` wheel),
  `subprocess` calls to native TOPP tools, and a Vue custom component.
- **uv's managed interpreters are not relocatable** — they bake in an absolute
  prefix. The build downloads a python-build-standalone `install_only` tarball.
- **`pyopenms==3.4.0` on macOS only.** The 3.5.0 macOS wheels ship both
  `libomp.dylib` and `libgomp.1.dylib`; importing aborts with `OMP: Error #15`.
  Marked `sys_platform == "darwin"` because 3.4.0 has no linux-aarch64 wheel.
- **Intel macOS is not built.** Those runners queued for hours while every other
  target finished in minutes.
- **Streamlit is unpinned** — see bug 8. This matters beyond hygiene: 1.60 exposes
  ~50 theme keys and `st.navigation(position="top")`, so the visual system is
  declarative config rather than CSS injection against internal class names.
- **The app writes `../workspaces-<repo>` relative to its cwd**, so it cannot run
  from a read-only resource directory. `main.js` copies the payload into `userData`
  on first run.
- **"Copy share link" is hidden on desktop** — Electron binds a random localhost
  port, so the URL means nothing to anyone else and differs next launch.
- **Signing is wired but dormant**: macOS entitlements exist (hardened runtime
  refuses to load `pyopenms`/`numpy`/`pyarrow` without `disable-library-validation`);
  Windows goes through SignPath, whose artifact configuration must expect a ZIP
  because `upload-artifact` always zips.

### Desktop asymmetry worth knowing

Workflow **input** is referenced in place (paths in `external_files.txt`). Results
added via **Add results** are **copied** — `link=True` is never passed in production.
Switching that on is decided but not implemented, and should ship together with the
"referenced file has moved" handling (clear failure + size/mtime fingerprint), or a
moved file becomes an unopenable dataset.

---

## 4. Design handoffs

Three arrived from Claude Design. Each was reviewed against the code before anything
was built; roughly a quarter of the last one was buildable.

| Handoff | Verdict |
|---|---|
| v1 — navigation/IA + presets | Preset catalogue named two components that do not exist (`flash_quant_view`, `conflict_resolution`) and shipped a preset that raised `KeyError` in the viewer. Design system it cited (`tokens/*.css`, logo SVG, a Font Awesome loader at a Hugo path) did not exist |
| v2 — same, plus a design system | Shipped real tokens, but they contradicted the README that came with them: six of seven cited colours absent, and **no status palette at all** while preset availability depends on three |
| v3 — wizard navigation | Much the best: reviewed the actual commit, cited real symbols. Still: its run model is unbuildable (three tools, three caches, three id namespaces, and one run produces one dataset per input file), its drop zone cannot infer the tool from filenames (`_deconv.mzML` is accepted identically by two tools), and its Workspace settings tab would have leaked per-session workspaces across tenants on the hosted deployment |

**Adopted from v3:** `st.navigation(position="top")` — the headline "remove the
sidebar" change turned out to be one keyword, keeping page URLs and history that a
hand-rolled router would have lost; workspace management in a dialog; step-named
workflow tabs; parsing given a visible phase; the viewer no longer gated on a run
this app performed.

**Two diagnoses from v3 that were right and are now fixed:** parsing was a silent
multi-minute phase, and the viewer claimed you had to run a workflow when adding
finished output is equally valid.

All reviews are in `../design-reviews/`.

---

## 5. Deferred with decisions recorded

`../design-reviews/file-management/DECISIONS.md`:

- **URI ingest**: `https://` everywhere with private ranges blocked; `file://`
  desktop-only.
- **Moved referenced files**: fail clearly, plus a size+mtime fingerprint.
- **Migration**: do **not** migrate existing workspaces. Consequence: filename-derived
  ids stay, so the SQL-injection surface was closed by parameterising instead — which
  protects old workspaces too.
- **Opaque dataset ids: rejected.** The upload pages use the stripped filename as a
  *join key*, deliberately: `sampleA_deconv.mzML` and `sampleA_annotated.mzML` must
  collide into one dataset. Minting ids per acquisition would produce four datasets
  where one is needed, and nothing would render.

In-flight cleanup plan and its adversarial review:
`../design-reviews/file-management/ADVERSARIAL-CLEANUP-PLAN.md`.

---

## 6. Things that will bite the next person

- **`st.tabs` renders every tab body on page load.** `execution()` reads
  `get_parameters_from_json()['FLASHTnT']` unguarded — it only works because the
  Method tab always rendered. Switching to lazy tabs gives a bare `KeyError` inside a
  detached `multiprocessing.Process`, visible only as `ERROR:` in a log file.
- **`FileManager.__init__` has side effects** — `mkdir` plus `CREATE TABLE`. Anything
  that iterates all three tools to ask a question will *create* caches for tools the
  user never opened.
- **SQLite connections must not outlive a script run.** Streamlit runs each rerun on
  a fresh thread; caching a `FileManager` in session state raises intermittently.
- **`save_parameters()` runs on every widget render**, so `params.json` exists after
  the first page load. Its existence proves nothing about user intent.
- **`upload_widget` auto-copies the example files** whenever its directory is empty,
  so "input present" is true after one visit with no user action.
- **Cache tag names are load-bearing**: `parseDeconv(**results)` works only because
  the tags equal the parser's parameter names. `parseTnT`'s do **not** match
  (`deconv_mzML` vs `out_deconv_mzML`), so it is called positionally.
- **Dataset ids are unique only within one tool's cache.**
- **The run log is wiped at the start of every run** and is per-tool, not per-dataset.
  There is no persisted record that a run completed, only `WORKFLOW FINISHED` in the
  current log.

---

## 7. What the wizard/data work added

Landed from design handoff v4 (`../design-reviews/handoff-v4/`), which is the
first of four handoffs that survived review largely intact — it shipped a
`05-STREAMLIT-LIMITS.md` enumerating what Streamlit cannot express and gave a
fallback for each, rather than specifying chrome that needs a Vue fork.

- **Recorded intent** (`<workflow_dir>/intent/{data,method}.json`). The one code
  change the design required, and it overrides the earlier "derive everything"
  decision for a good reason: `upload_widget` auto-copies example files when its
  directory is empty, and `save_parameters()` runs on every widget render, so
  both naive signals are true before the user has acted. Written only where a
  user action actually reached. Existing workspaces are not migrated, so a
  missing marker means *unknown*, never *no*.
- **The wizard banner** (`src/wizard.py` + `run_state`/`TOOLS` in `src/tools.py`).
  Six states including `skipped`, which is what makes FLASHQuant's absent Method
  and Run read as deliberate rather than broken.
- **File roles per tool** on `ToolSpec`, replacing the hand-written suffix
  chains. Two properties are load-bearing and tested: declaration order
  (FLASHQuant's `.tsv` is a catch-all) and the stripped filename as a join key.
- **`src/data_surface.py`**, one add/list/remove surface. Wired on FLASHQuant
  only so far — 237 lines to 83. FLASHDeconv and FLASHTnT still have their own
  copies, deliberately: the three have diverged and merging all at once would
  change behaviour unnoticed.
- **Confirmations** (`src/confirm.py`) for the two unbounded deletes.

### Still to do

- Migrate FLASHDeconv and FLASHTnT onto `data_surface`. Read each diff first;
  known drifts are listed in `../design-reviews/handoff-v4/03-DATA-SURFACE.md`.
- The example-load click has not been exercised end to end *through the new
  surface* in a browser — `tests/test_example_data.py` covers the same code path
  headlessly, but not the button.
- `06-IMPLEMENTATION-PLAN.md` from handoff v4 is unread.

## 8. Found during browser testing (post-v4)

Three defects, found by running the app in browser mode rather than headlessly.

**A silent no-op run reported success.** `execution()` validated its inputs with
`st.error(...)` + `return`. But `execution()` runs in the *detached* workflow
process, where `st.error` reaches no one, and `workflow_process()` then logged
`WORKFLOW FINISHED` over a run that did nothing. Starting FLASHDeconv with no
mzML selected produced an empty `results/`, a clean log, and a green wizard
banner. Both validation sites now raise, so the message lands in the log.

**The banner trusted `WORKFLOW FINISHED` alone.** That marker is written whenever
`execution()` returns without raising, so a TOPP tool that failed mid-run still
reached it. `run_state()` now checks for `ERROR` / `ERRORS OCCURRED` *before* the
finished marker. This was the exact "a wrong done is worse than none" risk the
plan flagged, and it had already materialised.

**Picking an input file marked the Method step configured.** `select_input_file`
writes into the same `params.json` as the method parameters, so the whole-file
diff recorded method intent on a Data-step action. `method_only()` now excludes
values that are paths under the workspace's own `input-files/` — recognised by
value, not by a key naming convention or a widget registration order that render
order controls.

### Still open

`Method: changed from defaults` can still be claimed after a run the user did not
configure. Remaining cause is upstream of the wizard: `save_parameters()` stores
`FLASHDeconv = {'SD:tol': '10.0\n10.0'}` as a non-default value although it *is*
the ini default — the `ini_value != value` comparison does not hold for
multi-valued TOPP parameters. Fixing it changes which parameters are written into
`params.json` and therefore what reaches the tools, so it wants a deliberate
change with its own test, not a drive-by. Cosmetic today: it over-reports
configuration, never under-reports it.

## 9. The released builds ship no TOPP tools

`build.sh` copies the TOPP binaries from `$OPENMS_BIN`, and CI never sets it, so
every published installer contains an empty `topp/`. build.sh says so itself —
`note: OPENMS_BIN unset, building without TOPP tools (Workflow pages will not
run)` — but it is a note in a build log, not a release note, so the shipped app
looks complete and then cannot run FLASHDeconv or FLASHTnT.

What the released app CAN do: add existing FLASHDeconv/FLASHTnT/FLASHQuant
output files and explore them in the viewers. That is a real use case and the
one FLASHQuant supports exclusively. What it CANNOT do: run a workflow.

Fixing this means building OpenMS per platform in CI (hours per target, and the
arm64/x64 macOS split doubles it) or downloading prebuilt TOPP binaries for each
of the five targets. Neither is a small change, and neither should happen
silently — it needs a decision about where those binaries come from.

Until then the release description should say the desktop app is a viewer for
existing results, not a self-contained analysis pipeline.

### Verified on the Intel build

macOS x64 (`macos-15-intel`) was checked end to end: both the Electron binary
and the bundled CPython report `x86_64`, the app launches, Streamlit answers
HTTP 200 on its random loopback port, and the Electron dialog server still
returns 403 without a token.
