# Markdown renderer

`markdown-it.min.js` is the browser UMD build from `markdown-it@15.0.2`, distributed under the MIT license in `markdown-it.LICENSE`. It is served locally; the page does not load a CDN.

To reproduce the vendor asset, run `npm ci --prefix apps/web --ignore-scripts`, then copy `apps/web/node_modules/markdown-it/dist/browser/markdown-it.umd.min.js` to this directory as `markdown-it.min.js`.

`markdown.js` disables raw HTML and images, keeps the parser's URL validation, and renders tables with a scrolling wrapper.
