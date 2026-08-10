data "archive_file" "this" {
  count       = var.package_type == "Zip" ? 1 : 0
  type        = "zip"
  source_dir  = var.source_dir
  output_path = "${path.module}/.build/${var.function_name}.zip"
  # Without this, a local sandbox with __pycache__/ present (from running
  # tests directly, not through the offline suites' throwaway venvs) zips
  # differently than a clean checkout - confirmed for real: the first
  # terraform-plan.yml run in CI showed all 3 zip-based Lambdas as
  # "will be updated in-place" on source_code_hash alone, because whatever
  # was actually applied locally had picked up stray __pycache__ dirs a
  # clean checkout never has. "__pycache__" alone only excludes a
  # top-level match (verified empirically) - **/ is needed for it to catch
  # every nesting depth (src/__pycache__, src/app/__pycache__, etc).
  excludes = ["**/__pycache__"]
  # Separate, real second cause of the same symptom: this sandbox's git
  # checkout produces 664-mode files (this machine's umask), but a fresh
  # clean-checkout test still showed a DIFFERENT hash than what CI computed
  # even after the __pycache__ fix above landed - meaning CI's checkout
  # (actions/checkout@v4) resolves a different default file mode (likely
  # 644, a common GitHub-runner umask) than this sandbox's git clone does.
  # archive_file bakes the OS's actual permission bits into the zip when
  # this isn't set, so two checkouts with identical file *content* still
  # hash differently. Verified locally: forcing this value produces an
  # identical hash regardless of the source files' actual on-disk mode.
  output_file_mode = "0644"
}

resource "aws_cloudwatch_log_group" "this" {
  name              = "/aws/lambda/${var.function_name}"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

data "aws_iam_policy_document" "assume_role" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "this" {
  name               = "${var.function_name}-lambda-role"
  assume_role_policy = data.aws_iam_policy_document.assume_role.json
  tags               = var.tags
}

# Scoped to this function's own log group only - not the AWS-managed
# AWSLambdaBasicExecutionRole, which grants logs:* on arn:aws:logs:*:*:*.
data "aws_iam_policy_document" "logs" {
  statement {
    actions = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = [
      "${aws_cloudwatch_log_group.this.arn}:*",
    ]
  }
}

resource "aws_iam_role_policy" "logs" {
  name   = "logs"
  role   = aws_iam_role.this.id
  policy = data.aws_iam_policy_document.logs.json
}

resource "aws_iam_role_policy" "additional" {
  # Every caller in this repo passes this, so it's unconditional - a count
  # gated on "!= null" doesn't work here anyway: the policy JSON embeds ARNs
  # from sibling resources being created in the same apply (e.g. a brand
  # new SQS queue's ARN), which are unknown at plan time, which makes the
  # null-check itself unresolvable and errors on `terraform plan` ("Invalid
  # count argument"). A plain resource argument tolerates "known after
  # apply" fine - only count/for_each can't.
  name   = "additional"
  role   = aws_iam_role.this.id
  policy = var.additional_policy_json
}

resource "aws_lambda_function" "this" {
  function_name = var.function_name
  description   = var.description
  role          = aws_iam_role.this.arn
  package_type  = var.package_type
  timeout       = var.timeout
  memory_size   = var.memory_size

  filename         = var.package_type == "Zip" ? data.archive_file.this[0].output_path : null
  source_code_hash = var.package_type == "Zip" ? data.archive_file.this[0].output_base64sha256 : null
  handler          = var.package_type == "Zip" ? var.handler : null
  runtime          = var.package_type == "Zip" ? var.runtime : null

  image_uri = var.package_type == "Image" ? var.image_uri : null

  environment {
    variables = var.environment_variables
  }

  tags = var.tags

  depends_on = [aws_cloudwatch_log_group.this, aws_iam_role_policy.logs]

  lifecycle {
    # Image-based services get their ongoing deploys from step 7's CI
    # (docker build -> ECR push -> `aws lambda update-function-code`), not
    # from repeated `terraform apply` - this stops a stale image_uri in
    # environments/prod from reverting a real CI deploy. Zip-based services
    # have no separate deploy path, so their filename/source_code_hash stay
    # fully Terraform-managed (not listed here).
    ignore_changes = [image_uri]
  }
}

resource "aws_lambda_event_source_mapping" "sqs" {
  # Gated on the plain boolean var.create_sqs_trigger, not on
  # "var.sqs_trigger_arn != null" - the ARN itself comes from a sibling SQS
  # queue created in the same apply and is unknown at plan time, and count
  # can't be based on an unknown value ("Invalid count argument"). The
  # caller already knows statically whether it's wiring a trigger, so that
  # decision is made with a literal true/false instead.
  count            = var.create_sqs_trigger ? 1 : 0
  event_source_arn = var.sqs_trigger_arn
  function_name    = aws_lambda_function.this.arn
  batch_size       = var.sqs_batch_size
}
