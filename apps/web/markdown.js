(() => {
  const markdown = window.markdownit({ html: false, breaks: true, linkify: false });
  // External Markdown is display content, not executable HTML or automatic remote images.
  markdown.disable("image");
  const linkOpen = markdown.renderer.rules.link_open;
  markdown.renderer.rules.link_open = (tokens, index, options, env, renderer) => {
    tokens[index].attrSet("target", "_blank");
    tokens[index].attrSet("rel", "noopener noreferrer");
    return linkOpen
      ? linkOpen(tokens, index, options, env, renderer)
      : renderer.renderToken(tokens, index, options);
  };
  markdown.renderer.rules.table_open = () =>
    '<div class="markdown-table" tabindex="0" role="region" aria-label="表格"><table>\n';
  markdown.renderer.rules.table_close = () => "</table></div>\n";
  window.financeRenderMarkdown = (target, text) => {
    target.innerHTML = markdown.render(String(text ?? ""));
  };
})();
