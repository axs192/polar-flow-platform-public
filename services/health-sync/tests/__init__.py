import os

# Force dummy AWS credentials/region for every test in this package, so the
# suite is hermetic regardless of the machine's ambient ~/.aws/config -
# moto mocks AWS API *responses*, but botocore still needs a resolvable
# region/credentials before that mocking kicks in. Without this, tests can
# accidentally "pass" on a machine that happens to have real AWS config
# (masking a real NoRegionError/NoCredentialsError a clean machine, or CI,
# would hit) - exactly what happened here before this was added.
os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
os.environ["AWS_ACCESS_KEY_ID"] = "testing"
os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
os.environ["AWS_SECURITY_TOKEN"] = "testing"
os.environ["AWS_SESSION_TOKEN"] = "testing"
