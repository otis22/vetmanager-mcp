# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| main branch | Yes |

## Reporting a Vulnerability

If you discover a security vulnerability in this project, please report it responsibly.

**Do NOT open a public GitHub issue for security vulnerabilities.**

### How to report

1. **GitHub Security Advisories** (preferred): use the "Report a vulnerability" button on the [Security tab](https://github.com/otis22/vetmanager-mcp/security/advisories) of this repository.
2. **Email**: send details to **otis22@gmail.com** with subject `[SECURITY] vetmanager-mcp`.

### What to include

- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

### Response timeline

- **Acknowledgment**: within 48 hours
- **Initial assessment**: within 7 days
- **Fix or mitigation**: as soon as reasonably possible, depending on severity

### Scope

The following are in scope:
- Authentication and authorization bypasses
- Credential or token leakage
- Injection vulnerabilities (SQL, command, XSS)
- CSRF bypasses
- SSRF via host resolution

Out of scope:
- Vulnerabilities in upstream Vetmanager REST API
- Issues requiring physical access to the server
- Social engineering attacks
