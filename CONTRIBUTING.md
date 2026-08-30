# Contributing to ReliefOS

Thank you for improving disaster-response coordination. This repository is safety-sensitive even
though it is an alpha MVP.

## Before opening a change

1. Open an issue describing the operational problem and affected user.
2. State whether the change touches prioritization, identity, medical data, recovery records,
   dispatch, routing, media verification, or authorization.
3. Do not include real disaster-victim data, credentials, phone numbers, identity documents, or
   graphic media in issues, fixtures, tests, or commits.

## Development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
make check
```

## Pull-request requirements

- Add or update automated tests.
- Preserve deterministic triage when Bedrock is unavailable.
- Never give a model authority to dispatch, reject, close, identify, or verify death.
- Keep public person-search responses free of exact location, phone, notes, and evidence.
- Document new environment variables and AWS permissions.
- Explain failure behaviour, idempotency, rollback, and audit implications.
- Use synthetic test data only.

All contributions are provided under the Apache License 2.0.
