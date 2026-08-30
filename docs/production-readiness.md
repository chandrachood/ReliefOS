# Production-readiness gate

ReliefOS must not be treated as operational emergency infrastructure until the responsible
authority accepts every applicable item below.

## Governance and operations

- Name the government system owner, incident commander, security owner, privacy officer, and
  24-hour technical support team.
- Approve P0-P4 definitions, dispatch authority, escalation timers, case-closure evidence, and
  responder-verification procedures.
- Approve medical, missing-person, deceased-person recovery, family-notification, and retention
  procedures.
- Establish an alternative reporting channel such as an official helpline or SMS gateway.
- Run tabletop and field simulations with actual participating agencies.

## Identity and authorization

- Deploy with `APP_ENV=production` and `AUTH_MODE=cognito` or an approved identity provider.
- Connect the PWA to authorization-code flow with PKCE; never place privileged tokens in source.
- Create government-managed coordinator and recovery-officer groups.
- Require MFA for privileged users and define emergency-access controls.
- Test every public, reporter, responder, medical, coordinator, and recovery-officer permission.

## Network and application protection

- Attach an AWS WAF web ACL in `us-east-1` to CloudFront.
- Configure managed rules, IP reputation, bot controls where appropriate, and tested rate limits.
- Add abuse controls that do not make genuine mass-surge reporting impossible.
- Restrict ALB traffic to CloudFront where the chosen AWS pattern permits it.
- Add Route 53, an approved domain, certificates, security headers, and origin-access controls.

## Data protection

- Classify public, operational, medical, identity, restricted-recovery, and audit data.
- Use separate S3 prefixes or buckets and IAM roles for restricted recovery media.
- Configure KMS keys, key policies, S3 object retention, malware scanning, and lifecycle deletion.
- Confirm DynamoDB point-in-time recovery, backup restoration, cross-Region recovery, and RTO/RPO.
- Prevent sensitive fields, authorization headers, media URLs, and victim data from entering logs.
- Complete a privacy impact assessment and jurisdiction-specific retention policy.

## Reliability

- Load-test case creation, idempotent retries, dashboard queues, SQS backlogs, and notifications.
- Prove that case creation works during Bedrock outage, media failure, and worker failure.
- Configure ECS autoscaling, SQS depth alarms, dead-letter alarms, DynamoDB alarms, and synthetic
  case-creation monitoring.
- Use at least two Availability Zones and remove single-NAT dependencies for critical production.
- Define Region-failover and data-reconciliation procedures.
- Test low bandwidth, intermittent connectivity, stale GPS, duplicate media, and device clock skew.

## AI evaluation

- Create a reviewed, synthetic multilingual evaluation set.
- Measure P0/P1 false negatives, unsupported claims, missing-information extraction, priority
  downgrade attempts, latency, and cost.
- Version the model, prompt, schema, tools, deterministic rules, and evaluation result.
- Require human approval for every consequential action.
- Define immediate model-disable and rollback controls.

## Maps and field truth

- Replace demonstration map tiles with the authority-approved map provider, such as Amazon
  Location Service.
- Ingest time-stamped road closures and field-verified hazards.
- Always display freshness and uncertainty; route computation is not route-safety verification.
- Provide printed, radio, and local-command alternatives when internet navigation is unavailable.
