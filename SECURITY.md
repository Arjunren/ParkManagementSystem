# Security Architecture and OWASP Review

## Security model

ParkFlow treats every browser value as untrusted. Authentication, role checks, object access, state transitions, slot eligibility, rates, totals, and change are enforced or recalculated in Flask. JavaScript provides only interaction enhancements.

Passwords are hashed with Werkzeug's `scrypt` implementation. Login responses are generic; repeated failures temporarily lock an account and endpoint rate limits add a second throttle. Login clears old session state. Password and role/account changes increment `session_version`, invalidating existing sessions. Reset tokens use `secrets.token_urlsafe`, are stored only as SHA-256 digests, expire, and are single-use.

`@login_required` and `@role_required(...)` guard sensitive routes. Customer history and receipt routes additionally scope records to the authenticated customer. Navigation visibility is only a presentation convenience, never the authorization boundary.

Flask-WTF protects state-changing requests with CSRF tokens. Jinja automatic escaping remains enabled and the codebase does not use the `safe` filter or assign untrusted strings through `innerHTML`. A restrictive Content Security Policy permits scripts, styles, connections, and forms only from the same origin.

SQLAlchemy ORM expressions parameterize queries. No user input is passed to a shell, `eval`, `exec`, dynamic imports, or template compilation. Validators constrain plates, slots, usernames, email addresses, amounts, IDs, dates, and field lengths on the server.

The entry and exit services lock relevant rows and commit related changes together. Each session snapshots an immutable rate version. An exit recalculates the amount server-side, validates payment, creates the payment, completes the session, and releases the slot in one transaction. Any failure rolls everything back.

Audit records cover authentication, authorization failures, user/role changes, entry, exit, payment, rates, slots, catalogs, and settings. Metadata is length-limited and known secret fields are redacted. There are no application routes to mutate or delete audit records.

## Security headers and transport

Responses set CSP with `frame-ancestors 'none'`, `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy`, `Cross-Origin-Opener-Policy`, and `X-Frame-Options`. HSTS is added only for HTTPS requests. Production cookies are Secure, HttpOnly, SameSite=Lax, and expire after a configured period.

Production must use HTTPS end-to-end from the client to the trusted reverse proxy. Keep Flask bound to a private interface and grant the MySQL account access only to the application database.

## Secret and payment handling

`.env` is ignored. The repository contains only `.env.example`. Production startup refuses a short/default secret or placeholder database URL. Logs and audit metadata must never contain passwords, reset tokens, session cookies, API keys, full card numbers, or CVV. ParkFlow records payment method and provider reference only; it is not a card-data vault or payment processor.

## OWASP Top 10 checklist

| Category | Implemented control | Primary location |
|---|---|---|
| Broken Access Control | Server-side role decorator, login checks, customer receipt/history ownership checks, authorization-denial audit | `app/security/decorators.py`, route modules |
| Security Misconfiguration | Separate configs, production validation, safe error pages, secure headers/cookies, no production debug | `config.py`, `app/security/headers.py`, `app/__init__.py` |
| Software Supply Chain Failures | Exact dependency pins, npm lockfile, minimal browser code, documented `pip-audit`/`npm audit` | `requirements.txt`, `package-lock.json`, `README.md` |
| Cryptographic Failures | Scrypt password hashing, CSPRNG reset tokens, digest-only token storage, HTTPS requirements | `app/models/__init__.py`, `app/routes/auth.py` |
| Injection | SQLAlchemy parameterization, centralized validators, no dynamic SQL/shell/eval, CSV formula neutralization | `app/security/validators.py`, `app/routes/reports.py` |
| Insecure Design | Explicit session states, row locks, atomic workflows, rate snapshot, server-side totals, immutable financial history | `app/services/parking_service.py`, `app/services/pricing_service.py` |
| Authentication Failures | Generic errors, endpoint limits, temporary lock, reset expiry/single use, session versioning | `app/routes/auth.py`, `app/__init__.py` |
| Software/Data Integrity Failures | No pickle/untrusted deserialization, no remote code/CDN at runtime, totals recomputed, migrations reviewed | service layer, compiled static assets |
| Logging and Monitoring Failures | Structured rotating application log and database audit trail for sensitive actions | `app/__init__.py`, `app/services/audit_service.py` |
| SSRF | No server-side URL fetch feature exists. Future URL features must allowlist schemes/hosts and block private/link-local/metadata addresses | architectural restriction |

Additional coverage includes CSRF tokens, CSP/XSS defenses, rate limiting, maximum request size, secure session cookies, non-destructive record retention, and generic 400/401/403/404/405/429/500 pages.

## Residual risks and deployment checklist

- MySQL row-lock behavior must be validated under the production isolation level and load. SQLite unit tests cannot prove concurrency safety.
- The default in-memory limiter is process-local. Production needs Redis or another shared Flask-Limiter backend.
- SMTP delivery security, SPF/DKIM/DMARC, and reset-mail observability are deployment responsibilities.
- The application does not implement MFA. Consider it for administrator accounts before internet exposure.
- The application records payments but does not contact GCash, Maya, or a card processor. Any future integration must use provider-hosted tokenization, signed webhooks, idempotency keys, and reconciliation.
- CSP is intentionally strict. Review it before adding analytics, external fonts, charts, or payment widgets; never weaken it broadly to solve an integration issue.
- Database backups, restore drills, log shipping/alerting, malware protection, OS patching, reverse-proxy hardening, and incident response remain operational controls.
- Audit rows are application-immutable but a database administrator can alter them. High-assurance installations should stream them to append-only external storage.
- Run dependency audits and tests on every change. Apply security upgrades promptly and review transitive dependencies before release.

## Vulnerability reporting

Do not open a public issue containing credentials, personal data, or an exploitable vulnerability. Report privately to the system owner with affected version, reproduction steps, impact, and suggested mitigation. Rotate any credential accidentally disclosed during investigation.
