# Third-party software notices

PDF Lens installs these tools into a private, version-specific environment. They are not embedded in the generated reader HTML. Versions are controlled by `requirements-runtime.txt` and the installer.

| Component | Use | License and upstream notices |
| --- | --- | --- |
| PyMuPDF / MuPDF | PDF text, glyph and page-image processing (`PyMuPDF==1.28.2`) | GNU AGPL v3; Artifex also offers a separate commercial license. See [PyMuPDF license and copyright](https://pymupdf.readthedocs.io/en/latest/about.html#license-and-copyright), [PyMuPDF upstream repository](https://github.com/pymupdf/PyMuPDF), and [MuPDF license](https://github.com/ArtifexSoftware/mupdf/blob/master/COPYING). |
| Playwright for Python | Browser-based reader verification (`playwright==1.63.0`) | Apache License 2.0. See [Playwright license](https://github.com/microsoft/playwright/blob/main/LICENSE) and [upstream repository](https://github.com/microsoft/playwright). |
| Chromium browser build | Browser used by Playwright verification | See Playwright's [browser installation and browser-cache documentation](https://playwright.dev/python/docs/browsers) and the license notices distributed with the installed browser build. |
| uv | Private Python and tool environment management | MIT or Apache License 2.0, at the user's option. See [uv license](https://github.com/astral-sh/uv#license) and [upstream repository](https://github.com/astral-sh/uv). |
| CPython 3.13 | Private managed interpreter installed by uv | Python Software Foundation License Agreement and applicable notices. See [Python license](https://docs.python.org/3/license.html) and [PSF licensing information](https://www.python.org/psf/license/). |

PDF Lens fetches the pinned runtime components from their upstream package and release sources during setup. Consult the license text and notices shipped with the exact installed release and browser build. This inventory identifies upstream components and links to their notices; it does not determine how any license applies to a particular deployment or use.
