# Third-party components

Apache-2.0 covers this project's original code. Dependencies and software in the
optional desktop image retain their own licenses.

- Vendored **markdown-it**: MIT; full license at
  [apps/web/vendor/markdown-it.LICENSE](apps/web/vendor/markdown-it.LICENSE).
- **Pi Agent Core**, **pi-ai**, and the **MCP TypeScript SDK**: MIT. Their license
  files are distributed with the installed npm packages.
- Python and npm dependencies are recorded in `uv.lock` and package lock files.
  Their licenses are distributed by their respective upstream packages.
- The Debian desktop image includes Debian, XFCE, Chromium, LibreOffice and other
  independently licensed software. Installed Debian package notices are available
  under `/usr/share/doc/<package>/copyright` inside the image. Node and npm package
  licenses are also retained in the image.

This is an attribution guide, not a relicensing of third-party software. Preserve
upstream notices when redistributing dependencies or desktop images.
