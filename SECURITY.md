# Security

This alpha is intended for one user on a trusted local machine. The workspace has
no login and the API must stay bound to loopback. Public hosting and multi-user
production deployment are not supported.

Keep `.env`, `.env.test`, `.runtime`, database files and credential vault keys out
of Git. Do not attach real emails, account data, tokens or unredacted logs to issues.
Google currently requests read-only Gmail and Calendar permissions. Exchange
queries are read-only; use keys without trading or withdrawal permissions.

MCP servers execute local programs. Only install and allow tools you trust. The
optional desktop container has network access and is not a complete security
boundary for hostile code. Treat external email, web pages and files as untrusted.

Before making a repository public, enable GitHub private vulnerability reporting
in repository settings. Report vulnerabilities through its Security tab rather
than a public issue. If private reporting is not available, contact the repository
owner privately; do not publish exploit details or credentials in an issue.

No production support or security response SLA is promised for this alpha.
