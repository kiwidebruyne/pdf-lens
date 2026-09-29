# Install PDF Lens in Codex

These instructions are for Codex to perform setup on the person's computer. The person only needs to paste an install request into Codex. Do not ask them to open Terminal, install Python, clone a repository or manage dependencies themselves.

## Download and verify the release

Get the latest published stable release from [PDF Lens on GitHub](https://github.com/kiwidebruyne/pdf-lens/releases). Download both `pdf-lens-VERSION.zip` and `pdf-lens-VERSION.zip.sha256`. Reject drafts and prereleases. Check that the archive SHA-256 exactly matches the checksum asset before extracting it to a temporary directory. Do not run files from an unverified archive.

Keep the extracted release directory until the installer reports success. Use its own bootstrap script so the installed code and release version match.

## Run the bootstrap

On macOS, invoke:

```sh
sh /path/to/extracted/pdf-lens/scripts/bootstrap.sh --source /path/to/extracted/pdf-lens
```

On Windows, invoke from PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File C:\path\to\extracted\pdf-lens\scripts\bootstrap.ps1 -Source C:\path\to\extracted\pdf-lens
```

Resolve `CODEX_HOME` if configured; otherwise the default is `~/.codex` on macOS or `%USERPROFILE%\.codex` on Windows. Bootstrap keeps uv, CPython 3.13 and PDF Lens dependencies in PDF Lens-owned directories under that Codex home. It does not require a system Python, Git or Node.js. Initial setup needs an internet connection.

On Windows, bootstrap may request elevation only when the managed PDF renderer reports a missing Microsoft Visual C++ runtime DLL. It verifies the downloaded Microsoft installer signature before requesting elevation. If setup fails, preserve the current known-good installation and report the actual error.

## Confirm success

Run the installed state action and inspect its active version, private runtime path and source snapshot:

```sh
codex_home=${CODEX_HOME:-"$HOME/.codex"}
sh "$codex_home/skills/pdf-lens/scripts/bootstrap.sh" --state
```

```powershell
$codexHome = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $HOME ".codex" }
powershell -ExecutionPolicy Bypass -File "$codexHome\skills\pdf-lens\scripts\bootstrap.ps1" -Action state
```

If `CODEX_HOME` is set to another location, resolve the installed skill under that path. Confirm that PDF Lens is installed, then tell the person they can attach a text-based English paper or textbook and specify the desired scope. Scanned PDFs are unsupported. A completed HTML reader works offline.

For later use, PDF Lens checks for the latest stable release automatically when a new work folder is prepared. In-progress work is resumed with its recorded runtime and source snapshot. See [setup, update and resume details](../references/setup.md).
