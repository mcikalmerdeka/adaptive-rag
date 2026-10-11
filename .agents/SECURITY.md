# Security Principles

## Mindset: Security Is Not a Feature

Security is a property of every decision, not a checkbox at the end. Treat every input as malicious until proven otherwise. Treat every dependency as compromised until audited. Treat every secret as leaked until rotated.

---

## The Security Checklist

Before shipping any code, verify these:

### Input Validation
- [ ] All user inputs are validated at trust boundaries (API, CLI, form, file upload)
- [ ] Validation happens before any processing — not as an afterthought
- [ ] Whitelist over blacklist: define what's allowed, not what's forbidden
- [ ] Type, length, format, and range are all constrained
- [ ] File uploads: check MIME type, extension, size, and scan for malicious content
- [ ] Deserialization: never blindly deserialize untrusted data (pickle, YAML, XML, JSON with custom decoders)

### Secrets Management
- [ ] No hardcoded secrets in source code (API keys, passwords, tokens)
- [ ] Environment variables or secret managers only
- [ ] `.env` files are in `.gitignore`
- [ ] No secrets in logs, error messages, or stack traces
- [ ] Rotate secrets when team members leave or when compromise is suspected
- [ ] Different secrets for dev/staging/prod — never share production keys with dev environments

### Authentication & Authorization
- [ ] Authentication on every endpoint that isn't explicitly public
- [ ] Principle of least privilege: users get the minimum access they need
- [ ] Never trust client-side authorization checks — verify on the server
- [ ] Session tokens: secure, httpOnly, sameSite cookies; short expiry with refresh tokens
- [ ] Rate limiting on auth endpoints (login, register, password reset)

### Data Protection
- [ ] Sensitive data encrypted at rest (database, files, backups)
- [ ] Sensitive data encrypted in transit (TLS 1.2+, no downgrade)
- [ ] PII minimized: collect only what's necessary, delete when no longer needed
- [ ] Database queries parameterized — never string-concatenate SQL
- [ ] No sensitive data in URL parameters or client-side storage

### Dependency Security
- [ ] Audit dependencies before adding them: maintenance status, known vulnerabilities, supply chain risk
- [ ] Pin versions in lock files; use `npm audit`, `pip-audit`, `cargo audit`
- [ ] Review what a dependency does before trusting it with secrets or user data
- [ ] Prefer well-maintained, widely-used libraries over obscure ones

---

## Common Attack Vectors

| Attack | Prevention |
|---|---|
| **Injection** (SQL, NoSQL, Command, LDAP) | Parameterized queries, input sanitization, avoid `eval`/`exec` |
| **XSS** (Cross-Site Scripting) | Escape output, Content-Security-Policy, sanitize HTML |
| **CSRF** (Cross-Site Request Forgery) | CSRF tokens, SameSite cookies, verify Origin header |
| **Path Traversal** | Canonicalize paths, whitelist allowed directories, no user-controlled paths |
| **SSRF** (Server-Side Request Forgery) | Whitelist outbound URLs, no user-controlled destinations |
| **Deserialization** | Avoid deserializing untrusted data; use safe formats (JSON with schema validation) |
| **IDOR** (Insecure Direct Object Reference) | Verify ownership on every resource access; use UUIDs not sequential IDs |
| **Race Conditions** | Atomic operations, proper locking, idempotent endpoints |

---

## Security-First Development Patterns

### Defensive Coding
```python
# BAD: Trusting user input
query = f"SELECT * FROM users WHERE id = {user_id}"

# GOOD: Parameterized query
cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
```

### Fail Securely
```python
# BAD: Default allow
if user.is_admin:
    allow_access()
else:
    deny_access()

# GOOD: Default deny
if not user.is_authenticated or not user.is_admin:
    raise PermissionDenied()
allow_access()
```

### Secure Defaults
- Framework security features enabled by default (CSRF protection, XSS filters)
- No debug mode in production
- No open CORS (`*`) in production
- No stack traces exposed to end users

---

## When to Escalate

Stop and ask the human when:
- Handling production secrets or credentials
- Modifying authentication/authorization logic
- Adding new external dependencies with network access
- Processing sensitive user data (PII, health, financial)
- Deploying to production environments
- Anything involving encryption key management

**Security is not "I'll fix it later." Security is now.**
