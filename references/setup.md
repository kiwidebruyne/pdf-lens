# Install, update and resume

This reference is for Codex to carry out setup on the user's behalf. Do not ask a novice user to install Python, Git, Node.js, uv or browser tooling manually. Initial setup and release updates need internet access. After a reader is built, opening its self-contained HTML needs no network access.

## First install

Use the latest published stable GitHub release. Download its `pdf-lens-VERSION.zip` and matching `pdf-lens-VERSION.zip.sha256` asset from [PDF Lens releases](https://github.com/kiwidebruyne/pdf-lens/releases), verify the archive SHA-256 against the checksum asset, and extract to a temporary directory. Do not install from a draft or prerelease. Preserve the downloaded release source until setup succeeds.

Run the bootstrap script from the extracted source directory:

```sh
sh scripts/bootstrap.sh --source /absolute/path/to/extracted/pdf-lens
```

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap.ps1 -Source C:\path\to\extracted\pdf-lens
```

The script installs uv and managed CPython 3.13 in a PDF Lens-owned directory under Codex home, then installs the skill and its version-specific PDF and browser-verification runtime. It does not require a system Python, Git or Node.js. It may install the Microsoft Visual C++ runtime on Windows only after detecting a missing runtime DLL, verifying Microsoft's signature and requesting elevation.

The active install state records the private interpreter as `runtime_path` and the matching source code as `source_snapshot`. Normal document work goes through the installed `scripts/run.py`; do not call the machine's unrelated system Python or the internal `paper_reader.py` directly.

Confirm installation with the installer state action. The default Codex home is `~/.codex` on macOS and `%USERPROFILE%\.codex` on Windows; if `CODEX_HOME` is configured, use that path:

```sh
codex_home=${CODEX_HOME:-"$HOME/.codex"}
sh "$codex_home/skills/pdf-lens/scripts/bootstrap.sh" --state
```

```powershell
$codexHome = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $HOME ".codex" }
powershell -ExecutionPolicy Bypass -File "$codexHome\skills\pdf-lens\scripts\bootstrap.ps1" -Action state
```

For an alternate test home, pass `--codex-home PATH` / `-CodexHome PATH` to bootstrap. Do not show that advanced override to a normal user unless troubleshooting requires it.

## Stable updates and pinned work

The installed `scripts/run.py prepare` checks for the latest published stable release only when creating a new work folder. It downloads the versioned release ZIP and checksum, verifies the archive, prepares and smoke-tests the matching runtime, then proceeds with the new work. If update fails, it keeps the current known-good release active and reports the failure; continue with that release where possible.

After a successful prepare, `output/pdf-lens/<document>.work/execution.json` records the runtime ID. The matching runtime metadata points to the retained `source_snapshot`. Resume, validate and build through `scripts/run.py`; it selects the work folder's pinned runtime and stops with a clear error if the snapshot is unavailable or does not match the prepared processor version. Do not update or mix source versions manually during a document.

## Continue a work folder

The user's source PDF, work folder and completed HTML are separate from the installed skill and runtime. A new work folder can use a newer stable release while existing work continues against its retained snapshot.

## Uninstall

Only uninstall when the user requests it. On macOS, resolve Codex home as above and run `sh "$codex_home/skills/pdf-lens/scripts/bootstrap.sh" --uninstall`. On Windows, resolve `$codexHome` as above and run `powershell -ExecutionPolicy Bypass -File "$codexHome\skills\pdf-lens\scripts\bootstrap.ps1" -Action uninstall`. It removes PDF Lens-owned skill/runtime files and leaves document work folders and generated readers in place. Do not manually remove shared Codex folders.

## Local v0.2.0 and legacy work

Install a tested checkout with `scripts/manage_install.py install --source PATH`. Updates never replace it with an equal or lower public release. Use `scripts/run.py migrate --work OLD --output NEW` for legacy v2 annotations; it copies the folder and leaves source PDF, extracted v2 artifacts and original execution.json unchanged. migration.json records original extraction and current processing runtime separately. Resume/build uses the new processing pin for the copied folder. Existing unmigrated jobs retain their old runtime.

## Local v0.3.0 live reader

Install the tested v0.3.0 checkout using the same local install command. It adds `serve` and `publish` without changing annotation v3. Existing work keeps its recorded runtime; a v0.2.0 pin does not gain live commands automatically. New v0.3.0 work can open the original preview before authoring, recover saved publications after restarting `serve`, and produce the final offline HTML automatically when coverage and reviews are complete.
