# Polar Flow Platform

> This is a public snapshot of a real personal project I built and operate against my own Polar/AWS accounts. Real account IDs, credentials, and infra state are excluded (see `.gitignore` / `CLAUDE.md`), so the AWS-deploy workflow and the live-account runbooks below describe infrastructure you'd need your own AWS account to actually run — the Terraform, tests, and CI are otherwise fully usable as-is.

Consolidated Terraform + CI/CD + application code + docs for the Polar Flow webhook pipeline (watch sync → webhook → SQS → Lambda ETL → DynamoDB/S3) plus a WhatsApp-based daily summary and Q&A assistant.

See [docs/architecture.md](docs/architecture.md) for the current-state understanding, architecture diagram, known issues, and the migration roadmap to the target state.

Status: early scaffold — see the roadmap checklist in the architecture doc for what's done vs. pending.

## Local setup

This repo uses [`uv`](https://docs.astral.sh/uv/) for all Python tooling — no `pip`/`pipx`/Poetry.

Every clone needs one one-time step before committing, since `.git/hooks/` isn't version-controlled:

```sh
uv tool install pre-commit
pre-commit install   # installs the git hook from .pre-commit-config.yaml
```

This wires up [gitleaks](https://github.com/gitleaks/gitleaks) to scan staged changes for secrets before every commit (fast, offline, no network calls — see `.pre-commit-config.yaml` for why it's pinned below v8.19). Heavier scans (full-history, container images, Terraform policy, dependency audits) run in CI instead, not on every local commit.

## Infrastructure

Terraform lives in `terraform/`. Order matters on a brand-new AWS account:

1. **`terraform/bootstrap`** — run once per new account, first. Creates the S3 bucket + DynamoDB table that everything else uses as its remote state backend. See its README.
2. **`terraform/environments/prod`** — the actual application stack (Lambdas, SQS, DynamoDB, API Gateway, etc.), built on top of the backend bootstrap just created. Has its own bootstrap order too (an ECR image has to exist before its Lambda can be created, and — separately — a real Polar user has to be onboarded and the webhook subscribed before the secret can be fully populated or anything can process a real watch sync) — see its README for the full step-by-step, including exactly how to get Polar API access.

None of the above is optional if you want a genuinely working end-to-end pipeline, not just infrastructure that exists. Three manual, non-scriptable, human-only steps sit inside that sequence — none of them have an API to script around: registering for Polar API access at [admin.polaraccesslink.com](https://admin.polaraccesslink.com/), setting up a Meta developer app + WhatsApp product to get the `META_*` credentials, and generating an OpenAI API key. Everything else (`terraform apply`, onboarding yourself as a Polar user, subscribing both webhooks, populating secrets) is scripted and documented in `terraform/environments/prod/README.md`, including where each of those three manual steps fits into the sequence.

To periodically re-validate that these bootstrap steps still work end-to-end (not just read correctly), see [`docs/runbooks/teardown-rehearsal.md`](docs/runbooks/teardown-rehearsal.md).

## Web app — AI running coach

`app/polar_web_app/` is a separate FastAPI app: an authenticated chat UI where an athlete asks a Claude-backed coach about their real Polar exercise data (pulled via `services/exercise-insights` as a local Python dependency). It doesn't deploy to AWS — it's built as a Docker image and run on a Raspberry Pi at home. See [app/polar_web_app/README.md](app/polar_web_app/README.md) for local setup, and [docs/runbooks/raspberry-pi-web-app.md](docs/runbooks/raspberry-pi-web-app.md) for the one-time Pi provisioning + deploy/update procedure, including the least-privilege AWS credential it needs (`terraform/environments/prod/web_app.tf`).

If exercise data hasn't been backfilled into this account yet, see [docs/runbooks/data-migration-backfill.md](docs/runbooks/data-migration-backfill.md) — run once, after the web app is confirmed working.

## CI/CD

Every PR gets `Test` and `Security scan` (bandit, pip-audit, Trivy container + Terraform config scans, full-history gitleaks) — both read-only, safe to run on any PR.

Actually changing the real account is **manual only, never automatic on merge** — a deliberate choice, not an oversight:

- **Terraform**: no CD workflow. Review + approve the PR, merge, then run `terraform apply` locally against the `polar-app-prod` CLI profile, following `terraform/environments/prod/README.md`'s documented sequence. Simpler than a `workflow_dispatch` gate for a solo repo, and it means `apply` never runs unattended in CI.
- **`deploy-service.yml`**: `gh workflow run deploy-service.yml -f service=exercise-etl` (or `health-sync`/`exercise-insights`) — builds, pushes a git-SHA-tagged image, and updates that one Lambda's code. Authenticates to AWS via GitHub Actions OIDC federation (`terraform/environments/prod/cicd.tf`) — no long-lived AWS keys stored in GitHub. See that file's comments for the exact IAM scoping. Needs your own AWS account, OIDC role, and an `AWS_DEPLOY_ROLE_ARN` repo *secret* (not a repo variable — GitHub Actions variables are plaintext-readable by anyone with read access to the repo, and this ARN contains the real account id) configured to actually dispatch — in a fresh fork it fails safely at the assume-role step with no credentials to leak.

## Contributing

Branch + PR, not direct pushes to `main`: branch off latest `main`, open a PR, wait for both CI workflows (`Test`, `Security scan`) to go green, then merge. This is a followed convention, not a GitHub-enforced rule — branch protection needs GitHub Pro on a private repo, which this one isn't on. See `CLAUDE.md`'s "Git workflow" section for the full reasoning.
