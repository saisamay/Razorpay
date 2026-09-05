import os

# Set fallback environment variables for test runs if not explicitly set
if not os.environ.get("ASSIGNMENT_SECRET_SALT"):
    os.environ["ASSIGNMENT_SECRET_SALT"] = "test_secret_salt_123"
