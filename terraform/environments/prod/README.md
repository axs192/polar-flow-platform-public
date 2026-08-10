# environments/prod

Builds the whole application stack fresh in the new `polar-app-prod` AWS account (`<account-id>` — real value in `~/.aws/config`, never committed; also fetchable via `aws sts get-caller-identity --profile polar-app-prod --query Account --output text`). Greenfield `apply` — nothing is imported, nothing here touches the old account.

## Prerequisites

- **Docker**, the **AWS CLI**, **Terraform**, and **`jq`** installed locally — used directly in the bootstrap sequence below (`docker build`/`push`, `aws ecr`/`secretsmanager`, `terraform apply`, and `jq` for the secret's get→merge→put steps so populating it doesn't clobber a value written by an earlier step).
- An AWS CLI profile named **`polar-app-prod`** already configured (`aws_profile`'s default in `variables.tf`) — this comes from having already created the AWS account and run `terraform/bootstrap` once; both are assumed done before this README starts.
- **`uv`** installed (see root [README.md](../../../README.md)) — `polar-onboarding` (used below) is a `uv`-managed CLI.

## What this creates

- **DynamoDB**: `exercise_data`, `health_metrics` (pay-per-request, point-in-time recovery on).
- **SQS FIFO**: `polar-webhook.fifo`, `exercise-message.fifo`, `user-query.fifo`, each with its own DLQ (3 delivery attempts before redrive) — the old account had none.
- **S3**: three buckets (health-metrics backfill data, exercise-insights' system prompts, the web app's per-user profile/conversation context), all versioned, SSE-encrypted, all public access blocked.
- **Secrets Manager**: one secret (`polar-app-prod/app-secrets`) — see "Secret keys" below. Deliberately just the container; no value is ever set through Terraform.
- **ECR**: one repo per Docker-based service (`exercise-etl`, `health-sync`, `exercise-insights`), immutable tags, lifecycle policy keeping the last 5 images.
- **Lambda**: all 6 real services (`polar-onboarding` is a local CLI, not deployed). Each gets its own least-privilege IAM role — no shared `lambda-ex`, no `SecretsManagerReadWrite`.
- **API Gateway**: one REST API, stage `prod` (not `development`, unlike the old account). `POST /webhook` → `webhook-authenticator`; `/messenger` GET → `whatsapp-webhook-verify` (Meta's handshake), POST → `whatsapp-inbound` — one callback URL for both, which is also what fixes `whatsapp-webhook-verify` being orphaned in the old account (no route existed there at all).
- **Monitoring**: an SNS topic (email) that a DLQ-has-messages alarm (all 3 queues) and a repeated-signature-failure alarm (`webhook-authenticator`, `whatsapp-inbound`) both publish to.
- **IAM user `rpi-web-app`** (`web_app.tf`): least-privilege credential for `app/polar_web_app` running on a Raspberry Pi outside this account — read-only on `exercise_data`, read/write on the web-app context bucket only. Terraform creates the user and its policy; the actual access key is generated out-of-band (see `web_app.tf`'s comment and [docs/runbooks/raspberry-pi-web-app.md](../../../docs/runbooks/raspberry-pi-web-app.md)), same "Terraform creates the container, never the credential" pattern as the Secrets Manager secret above.

## Bootstrap order — this cannot be a single `apply` on a truly fresh account

Two things are true regardless of how this is structured, and no Terraform trick removes them:

1. **The 3 image-based Lambdas need a real image in ECR before they can be created.** Lambda validates the image exists at `CreateFunction` time; Terraform has no resource that represents "an image was pushed," since that's a `docker push`, not infrastructure.
2. **The secret needs real values before anything that reads it will actually work**, and those values should never pass through a `.tf` file or Terraform state.

So the real sequence is:

```sh
cd terraform/environments/prod
cp terraform.tfvars.example terraform.tfvars   # fill in alert_email now; leave the image URIs as the example placeholders until step 3 below - you can't know the real tags until step 2 has actually pushed something
terraform init

# 1. First apply: creates everything EXCEPT the 3 image-based Lambda functions,
#    which will fail (expected - there's no image yet). Everything else -
#    DynamoDB, SQS+DLQs, S3, the secret container, ECR repos, the 2 zip-based
#    Lambdas, API Gateway, monitoring - succeeds in this same run.
terraform apply

# 2. Build and push a real initial image to each of the 3 ECR repos this just
#    created (see each service's Dockerfile). Use a real tag, not :latest -
#    the repos are image_tag_mutability = IMMUTABLE. v1 here is arbitrary -
#    just needs to be a real, explicit tag for this one manual push; step 7's
#    CI/CD switches to git-SHA tags for every deploy after this. Real account
#    ID for this profile, captured once rather than typed by hand each time.
#    Service names match both the ECR repo names and services/ directory
#    names exactly, so one loop covers all three - no copy-pasting per service.
ACCOUNT_ID=$(aws sts get-caller-identity --profile polar-app-prod --query Account --output text)

aws ecr get-login-password --profile polar-app-prod --region us-east-1 \
  | docker login --username AWS --password-stdin "$ACCOUNT_ID".dkr.ecr.us-east-1.amazonaws.com

for SERVICE in exercise-etl health-sync exercise-insights; do
  # ../../../services/$SERVICE, not services/$SERVICE - still in
  # terraform/environments/prod the whole time (see cd at the top of this
  # block), never left it.
  docker build -t "$ACCOUNT_ID".dkr.ecr.us-east-1.amazonaws.com/"$SERVICE":v1 "../../../services/$SERVICE"
  docker push "$ACCOUNT_ID".dkr.ecr.us-east-1.amazonaws.com/"$SERVICE":v1
done

# 3. Put the real tags into terraform.tfvars, then re-apply - this creates
#    the 3 remaining Lambda functions, now that their images exist.
#    to_mobile_number/from_mobile_number (see "Set up Meta/WhatsApp + OpenAI"
#    below) are also required by this point - placeholders are fine for now
#    if you haven't done that yet, same as the image URIs were before step 2;
#    set the real values and re-apply once you have them.
terraform apply
```

## Set up Meta/WhatsApp + OpenAI — populates part of the secret itself

The other manual, human-only steps in this bootstrap, alongside Polar registration below - nowhere else in this repo are these credentials sourced. Unlike Polar's onboarding flow below, subscribing the WhatsApp webhook triggers a real, immediate verification call against your account (Meta calls `GET` on the callback URL as soon as you subscribe), so this section writes its own secret values partway through, before that call happens - not batched into the single "populate the secret" step at the very end like the Polar-specific values are.

Meta's own [WhatsApp Cloud API get-started guide](https://developers.facebook.com/docs/whatsapp/cloud-api/get-started/) covers step 1 below with current screenshots - worth having open alongside this, since Meta's dashboard UI shifts around more often than this doc gets revisited.

```sh
# 1. Create the app itself, if you don't already have one:
#    developers.facebook.com -> log in / register as a developer if you
#    haven't -> My Apps -> Create App -> app type "Business" -> name + email
#    -> select the "Connect with customers through WhatsApp" use case ->
#    attach an existing Business Portfolio or create one when prompted.
#    This auto-creates a test WhatsApp Business Account (WABA) and a free
#    test phone number under WhatsApp -> API Setup in the app dashboard -
#    that test number is enough for everything below, no Meta Business
#    verification needed at personal scale.

# 2. Generate a PERMANENT access token - the "Generate access token" button
#    on the API Setup page only gives a 24h token, not enough for a real
#    deployment. Instead: business.facebook.com/settings -> System users ->
#    create one -> Assign assets -> add both this app AND the WhatsApp
#    Business account from step 1, each with full control -> Generate token,
#    selecting business_management, whatsapp_business_messaging,
#    whatsapp_business_management -> META_AUTH.

# 3. The app's own App Secret (App Dashboard -> Settings -> Basic -> App
#    Secret -> Show) is what whatsapp-inbound verifies inbound
#    X-Hub-Signature-256 HMACs against -> META_NOT_SEC.

# 4. Pick ANY string yourself - this one is reader-chosen, not Meta-provided,
#    easy to miss -> META_VERIFY_TOKEN. You'll enter this exact same string
#    into Meta's webhook configuration in step 6 below.

# 5. An OpenAI API key (platform.openai.com/api-keys) -> OPEN_AI_AUTH.

# 6. Write what you have so far into the secret NOW, before subscribing the
#    webhook in step 7 below - `terraform apply` only ever creates the
#    secret as an empty container (see "Secret keys" below), so until
#    something writes a real value, whatsapp-webhook-verify has no
#    META_VERIFY_TOKEN to check against. Subscribing the webhook first (the
#    old ordering here) makes Meta's live verification call fail every
#    single time on a fresh account - this has to happen first.
#    get→merge→put, not a plain put-secret-value: `put-secret-value`
#    REPLACES the secret's entire value, it does not merge - a plain write
#    here would be harmless on a brand-new empty secret, but the same
#    pattern gets reused later once other keys already exist, so build the
#    habit here. `|| echo '{}'` covers the brand-new-secret case, where
#    get-secret-value has nothing to return yet. file:// (not
#    --secret-string inline) avoids the value landing in shell history or
#    `ps aux`.
CURRENT_SECRET=$(aws secretsmanager get-secret-value --profile polar-app-prod --region us-east-1 \
  --secret-id polar-app-prod/app-secrets --query SecretString --output text 2>/dev/null || echo '{}')
echo "$CURRENT_SECRET" \
  | jq '. + {"META_AUTH": "...", "META_VERIFY_TOKEN": "...", "META_NOT_SEC": "...", "OPEN_AI_AUTH": "..."}' \
  > app-secrets.local.secrets.json
chmod 600 app-secrets.local.secrets.json
# Now open app-secrets.local.secrets.json in an editor and replace the "..."
# placeholders with the real values before running the next command.
aws secretsmanager put-secret-value --profile polar-app-prod \
  --secret-id polar-app-prod/app-secrets \
  --secret-string file://app-secrets.local.secrets.json
rm app-secrets.local.secrets.json   # delete once written - Secrets Manager is now the source of truth

# 7. Only now, in the app dashboard: Webhooks -> WhatsApp Business Account ->
#    Configure. Capture the real base URL once (same value used again in
#    "Onboard a real Polar user" below):
API_BASE=$(terraform output -raw api_base_url)
echo "$API_BASE/messenger"
#    Callback URL = the URL that just printed, Verify Token = the string
#    from step 4, then subscribe to the "messages" webhook field specifically.
#    Meta calls GET on this URL immediately to confirm (whatsapp-webhook-verify
#    handles this) - it must already be deployed (step 3 of "Bootstrap order"
#    above), AND step 6 above must already be done, or this fails.

# 8. Your own WhatsApp number (E.164, e.g. +15551234567) -> to_mobile_number
#    in terraform.tfvars. The test number's own ID from step 1 (WhatsApp ->
#    API Setup page, labelled "Phone number ID" - a numeric ID, not the
#    phone number itself) -> from_mobile_number.
```

## Onboard a real Polar user + subscribe the webhook — do this next, before populating the secret

Nothing downstream (secrets, a real watch sync, exercise-insights answering
questions) works without this. Like the Meta/WhatsApp setup above, Polar's
partner registration is a manual, human step on their site, not an API call
- everything *after* that registration, though, is scripted below.

```sh
# 0. One-time, per Polar developer account, done once in a browser (not
#    scriptable): register at https://admin.polaraccesslink.com/, signing in
#    with a Polar Flow account, and create a client. This is where client_id
#    and client_secret come from - there is no API for this step.

# 1. Get this account's real API base URL (the callback URL Polar will POST
#    webhook events to) - captured into a variable so step 4 below can
#    reuse it directly instead of retyping it:
API_BASE=$(terraform output -raw api_base_url)
echo "$API_BASE"
# -> https://<api-id>.execute-api.us-east-1.amazonaws.com/prod

cd ../../../services/polar-onboarding
uv sync   # one-time, creates .venv/ - uv run below picks it up automatically

# Put the client_id/client_secret from step 0 into a local .env here
# (gitignored, never committed) - cli.py loads it automatically, so none of
# the commands below need --client-id/--client-secret typed out (an explicit
# flag still overrides the .env value if you pass one).
cat > .env <<'ENV'
POLAR_CLIENT_ID=...
POLAR_CLIENT_SECRET=...
ENV
chmod 600 .env
# Now open services/polar-onboarding/.env (you're already in this
# directory) in an editor and replace the "..." with the real values from
# step 0.

# 2. Authorize yourself as a Polar user against this client. Opens a URL you
#    paste into a browser, log in with the Polar Flow account whose watch
#    data you want, authorize, then paste back either the bare code or the
#    full URL you land on. Returns access_token + x_user_id - save both,
#    nothing here writes them anywhere automatically.
uv run python -m src.cli authorize

# 3. Register that user (POST /v3/users). member-id is any identifier you
#    choose to represent this user in your own system, not a Polar concept -
#    reuse the x_user_id from step 2 if you don't need anything fancier.
#    Returns polar-user-id, which should equal x_user_id from step 2 - that's
#    the id every other service here calls user_id/POLAR_USER_ID.
#    access_token/member_id have no .env fallback (access_token is a
#    one-off value step 2 just printed, not a reusable credential) - typed
#    into variables below via `read`, not left as inline placeholder text,
#    so there's nothing plausible-looking to accidentally copy-paste as-is.
echo "Paste the access_token value from step 2's output, then press Enter:"
read -r ACCESS_TOKEN
echo "Paste the x_user_id value from step 2's output (or your own member id), then press Enter:"
read -r MEMBER_ID
uv run python -m src.cli register --access-token "$ACCESS_TOKEN" --member-id "$MEMBER_ID"

# 4. Create the webhook subscription, pointed at this account's real
#    callback URL from step 1 + "/webhook" (the route webhook-authenticator
#    listens on). --store-secret-name writes the response's
#    signature_secret_key straight into Secrets Manager as POLAR_WEBHOOK -
#    Polar's docs are explicit that this is the only chance to ever see that
#    value, so this isn't optional convenience, it's the only way to not
#    lose it. --aws-profile is required here, not optional the way it might
#    look - unlike every `aws` CLI call elsewhere in this doc, this step
#    goes through polar-onboarding's own boto3 calls, which otherwise fall
#    back to whatever your ambient default AWS credentials are - not
#    necessarily this account.
uv run python -m src.cli webhook create \
    --callback-url "$API_BASE/webhook" \
    --events EXERCISE,SLEEP \
    --store-secret-name polar-app-prod/app-secrets --region us-east-1 \
    --aws-profile polar-app-prod
```

After this, you have everything the next two steps need: `client_id`/
`client_secret` (step 0), `access_token`/`user_id` (step 2 - `user_id` is
step 2's `x_user_id`), and `POLAR_WEBHOOK` is already stored (step 4).
`META_AUTH`/`META_VERIFY_TOKEN`/`META_NOT_SEC`/`OPEN_AI_AUTH` are already in
the secret too - written earlier in "Set up Meta/WhatsApp + OpenAI"'s step 6,
before this section even started.

```sh
cd ../../terraform/environments/prod   # back to here for the rest

# 5. Populate the secret's remaining real values - just the Polar-specific
#    ones this section gathered (never through Terraform). Same get→merge→put
#    as "Set up Meta/WhatsApp + OpenAI"'s step 6 - POLAR_WEBHOOK and the
#    Meta/OpenAI keys are already in the secret by this point, and a plain
#    put-secret-value would silently replace the whole value and wipe them
#    out, not merge. file:// (not --secret-string inline) avoids the value
#    landing in shell history or `ps aux`.
CURRENT_SECRET=$(aws secretsmanager get-secret-value --profile polar-app-prod --region us-east-1 \
  --secret-id polar-app-prod/app-secrets --query SecretString --output text 2>/dev/null || echo '{}')
echo "$CURRENT_SECRET" \
  | jq '. + {"client_id": "...", "client_secret": "...", "access_token": "...", "user_id": "..."}' \
  > app-secrets.local.secrets.json
chmod 600 app-secrets.local.secrets.json
# Now open app-secrets.local.secrets.json in an editor and replace the "..."
# placeholders with the real values before running the next command.
aws secretsmanager put-secret-value --profile polar-app-prod \
  --secret-id polar-app-prod/app-secrets \
  --secret-string file://app-secrets.local.secrets.json
rm app-secrets.local.secrets.json   # delete once written - Secrets Manager is now the source of truth

# 6. Set polar_user_id in terraform.tfvars to the same id from step 2/3
#    above, then re-apply - this is what exercise-insights actually reads
#    exercise_data for when answering a question. Skipping this leaves
#    exercise-insights running against an empty user id: it deploys fine,
#    it just has no one's data to look up. If to_mobile_number/from_mobile_number
#    (see "Set up Meta/WhatsApp + OpenAI" above) are still placeholders,
#    set their real values now too - same apply covers both.
terraform apply
```

To update a single secret key later without retyping everything,
read-modify-write the same way `polar-onboarding`'s `set_secret_keys()` does
(`get-secret-value` → merge in Python/jq → `put-secret-value` again) rather
than reconstructing the whole JSON blob by hand.

After that first real image push, step 7's CI/CD takes over ongoing image builds/pushes (`docker build` → ECR push with a git-SHA tag → `aws lambda update-function-code`) — the module's `lifecycle { ignore_changes = [image_uri] }` means routine `terraform apply` runs afterward won't fight with what CI deployed.

## Verify it's actually working

Every step above can succeed and the pipeline can still be silently broken - none of it self-reports success. Check these before assuming it's done:

```sh
# 1. Confirm the SNS email subscription was actually accepted, not left
#    pending - if it's "PendingConfirmation", every alarm this stack has
#    (DLQ, signature-failure) is currently alerting into a void with no
#    error surfaced anywhere. Check your inbox for the confirmation email
#    if this still shows pending.
TOPIC_ARN=$(aws sns list-topics --profile polar-app-prod --region us-east-1 \
  --query "Topics[?contains(TopicArn,'polar-flow-platform-alerts')].TopicArn" --output text)
aws sns list-subscriptions-by-topic --profile polar-app-prod --region us-east-1 \
  --topic-arn "$TOPIC_ARN" --query 'Subscriptions[].SubscriptionArn'

# 2. Send a synthetic webhook - exercises webhook-authenticator's real HMAC
#    verification (raw hex HMAC-SHA256 of the body, header
#    Polar-Webhook-Signature) end to end, without needing a real watch sync.
#    Needs the real POLAR_WEBHOOK secret value (see "Secret keys" below).
API_BASE="$(terraform output -raw api_base_url)"
BODY='{"url":"test","event":"SLEEP"}'
SECRET="<the real POLAR_WEBHOOK value>"
SIGNATURE=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac "$SECRET" | sed 's/^.* //')
curl -i -X POST "$API_BASE/webhook" \
  -H "Content-Type: application/json" \
  -H "Polar-Webhook-Signature: $SIGNATURE" \
  -d "$BODY"
# Expect: 200 "Authenticated Correctly". A 401/exception means the signature
# or POLAR_WEBHOOK value is wrong; a 400 means the header didn't arrive.

# 3. Check each Lambda actually ran without error after step 2 (or a real
#    watch sync) - webhook-authenticator, then health-sync (SLEEP) or
#    exercise-etl (EXERCISE) downstream of it.
aws logs tail /aws/lambda/webhook-authenticator --profile polar-app-prod --region us-east-1 --since 5m
aws logs tail /aws/lambda/health-sync --profile polar-app-prod --region us-east-1 --since 5m
```

The real, final confirmation is a real Polar watch sync flowing all the way through to a WhatsApp message, and asking `exercise-insights` a real question over WhatsApp - everything above just narrows down where to look first if either doesn't happen.

## Secret keys

Every key every service's `config_loader()` actually reads, in one place (see each service's README for which specific keys it uses):

| Key | Used by |
|---|---|
| `client_id`, `client_secret`, `access_token`, `user_id` | exercise-etl, health-sync, webhook-authenticator (Polar Accesslink creds) |
| `POLAR_WEBHOOK` | webhook-authenticator (HMAC signing secret for the Polar webhook) |
| `META_AUTH` | health-sync, exercise-insights (WhatsApp Graph API send token) |
| `META_VERIFY_TOKEN` | whatsapp-webhook-verify (Meta's GET handshake) |
| `META_NOT_SEC` | whatsapp-inbound (`X-Hub-Signature-256` HMAC secret) |
| `OPEN_AI_AUTH` | exercise-insights |

One secret, not split by integration: matches the old account's real model exactly (see docs/architecture.md's Cost Considerations), and — more binding than cost — every service's `config_loader()` reads exactly one secret by name with no support for merging multiple. Splitting would need a code change this step doesn't make; noted as a legitimate future improvement, not silently dropped.

`client_id`/`client_secret` come from Polar's partner admin portal, `access_token`/`user_id` from `polar-onboarding authorize`+`register`, and `POLAR_WEBHOOK` is written automatically by `polar-onboarding webhook create --store-secret-name` — see "Onboard a real Polar user" above for all three. `META_*`/`OPEN_AI_AUTH` have no equivalent CLI helper; those are a manual get→merge→put (see "Set up Meta/WhatsApp + OpenAI"'s step 6 above — done earlier than the other keys, since subscribing the WhatsApp webhook triggers a live verification call that needs `META_VERIFY_TOKEN` already in place).

## Why a plain `apply` fails partway on a fresh account (and that's fine)

Terraform doesn't apply atomically across unrelated resources — a resource that can't be created (the 3 image-based Lambdas, before step 2 above) simply doesn't get created, while everything else in the same run still succeeds. Re-running `terraform apply` after pushing images picks up exactly where it left off. This is standard, expected behavior for this kind of ECR/Lambda bootstrapping order, not a bug in this config.

## Tearing it down

`terraform destroy` walks the same dependency graph in reverse and deletes everything this config manages. Fast, but not risk-free — read this before running it against anything with real data in it.

To periodically rehearse a full teardown-and-rebuild (validating this doc's bootstrap steps still work, not just read correctly) without risking real data, see [`docs/runbooks/teardown-rehearsal.md`](../../../docs/runbooks/teardown-rehearsal.md).

```sh
cd terraform/environments/prod
terraform plan -destroy   # read this fully before the next line - shows exactly what would be deleted
terraform destroy
```

Things worth knowing beforehand:

- **This deletes real data, not just infrastructure.** Destroying `exercise_data`/`health_metrics` deletes the actual rows; destroying the S3 buckets deletes the actual objects. Point-in-time recovery on the DynamoDB tables protects against accidental *writes* (e.g. a bad deploy), not against a deliberate `destroy`.
- **The S3 buckets will refuse to delete if non-empty** (`force_destroy` is deliberately not set on either) — empty them first, or accept that `destroy` will error on that resource specifically and stop there.
- **All three app S3 buckets (`health_metrics`, `prompts`, `web_app_context`) have `lifecycle { prevent_destroy = true }`, and both DynamoDB tables have `deletion_protection_enabled = true`** (added after a hung `terraform-apply.yml` run once computed a plan that would have replaced a data bucket — see `docs/architecture.md`'s incident writeup). `terraform destroy` hard-errors on all 5 resources until these are removed on purpose: the S3 `lifecycle` blocks in `s3.tf`/`web_app.tf`, and `deletion_protection_enabled` in `terraform/modules/dynamodb_table/main.tf`. Same intent as bootstrap's tripwire below — it shouldn't be easy to do by accident, and it should be restored afterward if the destroy was only a rehearsal, not a real teardown.
- **`terraform/bootstrap` must be destroyed *after* this, never before** — this config's state lives in the S3 bucket bootstrap created. Destroy bootstrap first and you've orphaned this state with no clean way to `destroy` these resources anymore (you'd be deleting things by hand in the console). If you ever do want to tear down *everything*, this direction, in this order:
  ```sh
  cd terraform/environments/prod && terraform destroy
  cd ../../bootstrap && terraform destroy   # will also refuse - see below
  ```
- **`terraform/bootstrap`'s state bucket has `prevent_destroy = true`** on it specifically — a deliberate tripwire, not a bug. `terraform destroy` will hard-error on that one resource rather than delete your state storage. You'd have to remove that `lifecycle` line on purpose first, which is the point: it shouldn't be easy to do by accident.
- **Secrets aren't part of any of this either way** — Terraform only ever manages the empty secret *container* (see "Secret keys" above), so destroying it just removes the container; the real credential values were never in Terraform's state to lose.
