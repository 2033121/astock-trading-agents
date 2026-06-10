# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.1.x   | Yes       |

## Reporting a Vulnerability

If you discover a security vulnerability, please **do not** open a public GitHub issue.

Instead, please report it via:

1. **GitHub Private Vulnerability Report** — Go to the repository's Security tab and click "Report a vulnerability"
2. **Direct contact** — Reach out to the maintainer via GitHub profile

Please include:

- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

We will acknowledge your report within 48 hours and aim to provide a fix within 7 days for critical issues.

## Security Best Practices

When using this project:

- **Never** hardcode API keys in source code or configuration files
- Use environment variables for all secrets (`OPENAI_API_KEY`, `TUSHARE_TOKEN`, etc.)
- Keep dependencies up to date: `pip install --upgrade astock-trader`
- Review `.env` files and ensure they are in `.gitignore` before committing

## Dependencies

This project depends on several third-party packages. Known vulnerabilities in dependencies are tracked via GitHub's Dependabot alerts when enabled.
