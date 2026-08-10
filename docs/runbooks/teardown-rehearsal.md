# Runbook: full teardown-and-rebuild rehearsal

Periodically validate that `terraform/environments/prod/README.md`'s bootstrap
steps still work end-to-end on a real account — not just that they read
correctly. This is the only way to catch the doc silently drifting from
reality (exactly what happened once already: the "Tearing it down" section
didn't mention `prevent_destroy`/`deletion_protection_enabled` until this
rehearsal caught it missing).

**Do this only when `exercise_data`/`health_metrics` have 0 items and both S3
buckets have 0 objects.** Check first:

```sh
aws dynamodb describe-table --table-name exercise_data --profile polar-app-prod --query 'Table.ItemCount'
aws dynamodb describe-table --table-name health_metrics --profile polar-app-prod --query 'Table.ItemCount'
aws s3 ls s3://<health-metrics-bucket> --recursive --profile polar-app-prod | wc -l
aws s3 ls s3://<prompts-bucket> --recursive --profile polar-app-prod | wc -l
```

If any of those are non-zero, this rehearsal deletes real data — stop and
reconsider, don't just proceed. Also check `aws secretsmanager describe-secret
--secret-id polar-app-prod/app-secrets --query VersionIdsToStages` — if this
isn't `null`, a real Polar webhook subscription may already point at this
account's API Gateway URL, which the rebuild will change (a fresh REST API
gets a new random API ID) and break until re-pointed via `polar-onboarding
webhook update`.

## Scope: `environments/prod` only, never `bootstrap`

Leave `terraform/bootstrap` (the remote-state S3 bucket + DynamoDB lock
table) alone. It's infrastructure-*for*-infrastructure, not an app service —
destroying it orphans the state needed to destroy/rebuild anything else, and
its own state bucket has the same `prevent_destroy` tripwire for exactly this
reason. `terraform/environments/prod/README.md`'s "Tearing it down" section
spells out the ordering if a full account wipe is ever genuinely intended;
that's a different, bigger operation than this rehearsal.

## Step 1 — temporarily disable the destroy protections

Two hardening measures added after a real incident (see
`docs/architecture.md`) will hard-error a plain `terraform destroy`:

- `lifecycle { prevent_destroy = true }` on both `aws_s3_bucket` resources in
  `terraform/environments/prod/s3.tf`
- `deletion_protection_enabled = true` in
  `terraform/modules/dynamodb_table/main.tf` (shared by both tables)

Flip all four to `false`. Don't delete the lifecycle blocks or the line —
just the boolean, so restoring them later is a one-character diff, not a
rewrite:

```hcl
# s3.tf, both aws_s3_bucket resources
prevent_destroy = false  # TEMP: teardown rehearsal <date> - revert after rebuild

# modules/dynamodb_table/main.tf
deletion_protection_enabled = false  # TEMP: teardown rehearsal <date> - revert after rebuild
```

Don't commit this state. It's purely transient and gets reverted before the
rehearsal finishes — `terraform plan`/`apply`/`destroy` read your local
working tree directly regardless of what's committed, so there's no need to
push a "protections disabled" commit to any branch. Skip straight to Step 2.

## Step 2 — plan, review, destroy

```sh
cd terraform/environments/prod
terraform plan -destroy -out=/tmp/destroy.tfplan
terraform show /tmp/destroy.tfplan   # read this fully - confirm it's only environments/prod's ~90 resources, nothing in bootstrap
terraform apply /tmp/destroy.tfplan
```

Expect something like `Plan: 0 to add, 0 to change, 90 to destroy` — no
adds, no changes, just deletes. If anything shows as "to add" or "to change"
alongside the destroys, stop and figure out why before applying; it likely
means a stray `-var` override or uncommitted unrelated edit is in play, not
real destroy-plan behavior.

## Step 3 — rebuild from the documented bootstrap order

Follow `terraform/environments/prod/README.md` from the top, exactly as a
first-time clone would:

1. `terraform apply` (creates everything except the 3 image-based Lambdas —
   expected to fail on those specifically).
2. Build + push a real image to each of the 3 ECR repos it just created.
3. `terraform apply` again (creates the 3 remaining Lambdas).
4. Onboard a real Polar user + subscribe the webhook (`polar-onboarding`
   CLI — needs a real `client_id`/`client_secret` from
   [admin.polaraccesslink.com](https://admin.polaraccesslink.com/)).
5. Populate the secret's remaining keys, set `polar_user_id`, final `apply`.

**A destroy wipes the *entire* secret, not just the Polar-specific keys.**
`terraform/environments/prod/secrets.tf` deliberately never manages the
secret's contents, only the empty container (see "Secret keys" in
`terraform/environments/prod/README.md`) — so `terraform destroy` takes
`META_AUTH`/`META_NOT_SEC`/`META_VERIFY_TOKEN`/`OPEN_AI_AUTH` down with it
exactly the same as `client_id`/`client_secret`/`access_token`/`user_id`/
`POLAR_WEBHOOK`. Confirmed directly against a real rehearsal via CloudTrail
(`DeleteSecret` followed by a fresh `CreateSecret` under a new ARN suffix -
Secrets Manager assigns that suffix once, permanently, at creation, so a
different suffix after a rebuild is conclusive proof everything was wiped,
not merely updated). Check what actually survived a rebuild rather than
assuming:

```sh
aws secretsmanager get-secret-value --profile polar-app-prod --region us-east-1 \
  --secret-id polar-app-prod/app-secrets --query SecretString --output text \
  | python3 -c "import json,sys; print(sorted(json.load(sys.stdin).keys()))"
```

If this is a pure rehearsal you're throwing away afterward, steps 4–5 can be
skipped once steps 1–3 are confirmed to work — the goal is validating the
Terraform/Docker/ECR bootstrap sequence, not necessarily re-registering a
real webhook subscription every time. **But if you intend to keep using the
rebuilt account for real** (not discard it), step 5 alone isn't enough:
redo *all* of `terraform/environments/prod/README.md`'s manual secret
population - "Set up Meta/WhatsApp + OpenAI"'s step 6 (`META_*`/
`OPEN_AI_AUTH`) *and* "Onboard a real Polar user"'s webhook create + final
populate step (`client_id`/`client_secret`/`access_token`/`user_id`/
`POLAR_WEBHOOK`) - since a partial re-populate (e.g. only the Polar half)
leaves `health-sync`/`exercise-insights`/`whatsapp-webhook-verify`/
`whatsapp-inbound` silently running against missing config, not an obvious
error at rebuild time.

**Known gotcha: step 1's `apply` can fail on the secret with "already scheduled
for deletion."** `terraform destroy` (Step 2 above) doesn't delete the
Secrets Manager secret immediately — AWS schedules it for deletion with a
30-day recovery window by default, and won't let a new secret reuse that
exact name (`polar-app-prod/app-secrets`) until that window clears. Since
this secret never holds real content through Terraform anyway (see "Secret
keys" in `terraform/environments/prod/README.md` — it's always an empty
container, populated out-of-band), it's safe to force-delete it immediately
instead of waiting:

```sh
aws secretsmanager delete-secret --secret-id polar-app-prod/app-secrets \
  --force-delete-without-recovery --profile polar-app-prod --region us-east-1
```

Then retry `terraform apply`. Don't "fix" this by adding
`recovery_window_in_days = 0` to the Terraform resource itself — that would
remove the recovery window for real, non-rehearsal deletions too, which is
exactly the kind of protection `prevent_destroy`/`deletion_protection_enabled`
elsewhere in this stack exist to preserve. This is a one-off manual step for
the rehearsal case specifically, not a config change.

## Step 4 — restore the destroy protections

Flip all four booleans from Step 1 back to `true`, `terraform plan` to
confirm the diff is exactly those two DynamoDB attributes (S3's
`prevent_destroy` is Terraform-client-side only and never shows as a
provider diff), then commit — this is the one part of the rehearsal that
*should* land in git, since it's a permanent, non-alarming diff (protections
back on, nothing else changed). Branch + PR, per this repo's normal
workflow — don't merge to `main` without review, same as always.

## Troubleshooting: stale state lock after an interrupted command

If a `plan`/`apply`/`destroy` gets interrupted before it finishes (Ctrl-C,
closed terminal, killed session) partway through, the DynamoDB state lock
isn't released automatically — the next command fails with `Error acquiring
the state lock` / `ConditionalCheckFailedException`.

Before force-unlocking, confirm nothing is actually still running against
this state — force-unlocking while a real operation is in flight can corrupt
state:

```sh
ps aux | grep terraform
```

If nothing's running, the lock is stale. The error message includes the
lock ID; force-unlock with it:

```sh
terraform force-unlock <lock-id>
```

This only clears Terraform's own bookkeeping — it doesn't touch any real AWS
resource, so it's safe once you've confirmed no other Terraform process is
actually running.
