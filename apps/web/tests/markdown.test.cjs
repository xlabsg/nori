const assert = require('node:assert/strict');
const test = require('node:test');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
function render(text) {
  const context = {window:{}, atob, TextDecoder, TextEncoder};
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../vendor/markdown-it.min.js'),'utf8'), context);
  context.window.markdownit = context.markdownit;
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../markdown.js'),'utf8'), context);
  const node = {};
  context.window.financeRenderMarkdown(node, text);
  return node.innerHTML;
}
test('software table is rendered with actual header and body cells', () => {
  const html = render('**桌面快捷方式**\n\n| 图标 | 程序 | 软件 |\n| --- | --- | --- |\n| 浏览器 | 网页浏览器 | Chromium |\n| 表格 | 电子表格 | Calc |');
  assert.match(html, /<strong>桌面快捷方式<\/strong>/);
  assert.match(html, /<th>图标<\/th>/);
  assert.match(html, /<td>Chromium<\/td>/);
  assert.equal((html.match(/<td>/g)||[]).length,6);
  assert.match(html, /class="markdown-table"/);
});
test('untrusted HTML, script links and remote images remain inert', () => {
  const html = render('<script>alert(1)</script>\n<img src=x onerror=alert(1)>\n[bad](javascript:alert%281%29)\n![remote](https://external.example/tracker.png)');
  assert.ok(!html.includes('<script>'));
  assert.ok(!html.includes('<img'));
  assert.ok(!html.includes('href="javascript:'));
  assert.ok(!html.includes('<iframe'));
});
test('lists, code and ordinary links render without losing syntax', () => {
  const html = render('- 第一项\n- 第二项\n\n```python\nprint("<safe>")\n```\n\n[文档](https://example.com)');
  assert.match(html, /<ul>/);
  assert.match(html, /<pre><code/);
  assert.match(html, /&lt;safe&gt;/);
  assert.match(html, /rel="noopener noreferrer"/);
});
