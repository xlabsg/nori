# Nori roadmap

Primary product reference: ChatGPT dots. The proposed focus is a self-hostable
assistant for ongoing personal work; finance tools remain optional extensions.
See [product direction](product-direction.md) for positioning and capability gaps.

The current milestone is an open-source local alpha: chat, tools/MCP, persistent
jobs and reminders, Google read-only connectors and an optional Linux desktop.
A fresh installation never creates user tasks automatically.

Deferred ideas (not release requirements or implemented features):

- More precise task-intent recognition before allowing task mutations.
- A documented connector extension interface beyond the current Google adapter.
- More detailed execution diagnostics and traces.
- A remote server runner, external asynchronous analysis, production authentication
  and multi-user isolation.

The original product design is exploratory; README and implementation documentation
state what is available now. Feature requests should start with a concrete workflow.
