# Security audit and release fixes

Date: 2026-08-30  
Scope: ReliefOS application, web portal, tests, packaging, and CI configuration

## Summary

The repository was reviewed for application-security weaknesses, correctness issues, dependency
vulnerabilities, and release blockers. The fixes below were applied and validated locally.

## Fixes applied

### 1. Broken development dependency

- **Issue:** `pyproject.toml` declared `httpx2>=2.12,<3`, which is not the HTTPX package used by the
  test suite and caused clean development/CI installations to fail.
- **Fix:** Replaced it with `httpx>=0.28,<1`.
- **Impact:** Development dependencies can now be installed from a clean environment.

### 2. Vulnerable test dependency constraint

- **Issue:** The project constrained pytest to versions below 9. The installed version was reported
  by `pip-audit` as affected by `PYSEC-2026-1845`.
- **Fix:** Updated the constraint to `pytest>=9.0.3,<10` and verified the suite with pytest 9.1.1.
- **Impact:** The known pytest vulnerability is no longer present in the validated environment.

### 3. Insufficient production secret validation

- **Issue:** Production configuration rejected only the literal development secret. A different but
  trivially short secret could still be accepted for case-access token generation.
- **Fix:** Production now requires `CASE_ACCESS_SECRET` to be unique and at least 32 characters.
- **Impact:** Reduces the risk of case-access tokens being forged through an easily guessed HMAC key.

### 4. Local media upload tickets did not expire

- **Issue:** Local upload responses advertised a 900-second expiry, but tickets remained valid until
  used or until the process stopped.
- **Fix:** Tickets now store a monotonic expiration timestamp and are rejected after 900 seconds.
- **Impact:** Limits the useful lifetime of a leaked development upload credential.

### 5. Malformed `Content-Length` caused an internal error

- **Issue:** The local media endpoint converted `Content-Length` directly to an integer. Invalid
  values could raise an uncaught exception and return HTTP 500.
- **Fix:** Invalid and negative values now produce HTTP 400; oversized values continue to produce
  HTTP 413.
- **Impact:** Prevents malformed requests from reaching an unhandled error path.

### 6. Cognito token validation hardening

- **Issue:** Signature, issuer, expiry, audience/client, and token-use validation existed, but the
  code did not explicitly require all critical claims and recreated the JWKS client per request.
- **Fix:** JWT validation now explicitly requires `exp`, `sub`, and `token_use`. JWKS clients are
  cached by issuer while retaining signature and issuer verification.
- **Impact:** Rejects structurally incomplete tokens and avoids unnecessary repeated JWKS client
  creation.

### 7. Missing browser security headers

- **Issue:** Application responses did not set a browser security baseline.
- **Fix:** Added the following headers:
  - `Content-Security-Policy`
  - `Referrer-Policy: no-referrer`
  - `X-Content-Type-Options: nosniff`
  - `X-Frame-Options: DENY`
  - `Permissions-Policy`
  - `Strict-Transport-Security` in production
- **Impact:** Reduces exposure to content injection, clickjacking, MIME sniffing, referrer leakage,
  and unnecessary browser capabilities.

### 8. Third-party frontend assets lacked integrity checks

- **Issue:** Leaflet JavaScript and CSS were loaded from a CDN without Subresource Integrity.
- **Fix:** Added pinned SHA-256 integrity hashes and anonymous CORS attributes to both assets.
- **Impact:** Browsers reject altered CDN resources that do not match the expected content.

### 9. Regression coverage

- Added coverage for weak production secrets.
- Added coverage for malformed local-upload `Content-Length` values.
- Added coverage for required response security headers.

## Verification results

The final local validation completed successfully:

| Check | Result |
| --- | --- |
| Test suite | 32 passed |
| Application coverage | 80.26% |
| Ruff lint | Passed |
| Ruff formatting | Passed |
| Mypy type checking | Passed |
| Python dependency audit | No known vulnerabilities found |
| Credential-pattern scan | No committed credentials found |

## Repository status

- Git repository initialized on branch `main`.
- Initial audited source commit: `d6d3c0b Harden ReliefOS for initial release`.
- GitHub publication remains pending because no remote is configured and the saved GitHub CLI
  credential for `chandrachood` is invalid. Re-authenticate with `gh auth login -h github.com`, then
  configure or create the intended remote before pushing.

## Operational limitations

Passing this audit does not by itself make ReliefOS production-ready emergency infrastructure.
Complete the governance, identity, privacy, resilience, mapping, AI-evaluation, and incident-response
controls in `docs/production-readiness.md` before operational deployment.
