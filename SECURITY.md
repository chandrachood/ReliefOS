# Security policy

## Supported versions

ReliefOS is currently an alpha project. Security fixes are applied to the latest `main` branch.

## Report a vulnerability

Do not open a public GitHub issue for a suspected vulnerability. Use GitHub's private security
advisory feature after the repository is published, or contact the repository owner through the
private security address configured in the GitHub project.

Include affected versions, reproduction steps using synthetic data, impact, and suggested
mitigations. Do not test against a live disaster deployment or access victim data.

## Deployment warning

The default local authentication mode trusts development headers. It is intentionally rejected
when `APP_ENV=production`. A real deployment must use Cognito or an approved identity provider,
least-privilege roles, monitored audit logs, protected media, tested backups, incident response,
and jurisdiction-specific data-retention rules.
