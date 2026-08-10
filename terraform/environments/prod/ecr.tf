locals {
  ecr_repo_names = ["exercise-etl", "health-sync", "exercise-insights"]
}

resource "aws_ecr_repository" "this" {
  for_each             = toset(local.ecr_repo_names)
  name                 = each.value
  image_tag_mutability = "IMMUTABLE" # git-SHA tags going forward (see docs/architecture.md's fixes-baked-in), not floating :latest

  image_scanning_configuration {
    scan_on_push = true
  }
}

# Keep last 5 images per repo, to cap storage cost (see Cost Considerations
# in docs/architecture.md).
resource "aws_ecr_lifecycle_policy" "this" {
  for_each   = aws_ecr_repository.this
  repository = each.value.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Keep last 5 images"
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = 5
        }
        action = {
          type = "expire"
        }
      }
    ]
  })
}
