import os

# Unit/API tests must never read credentials from a developer's local .env file.
os.environ["SUPABASE_URL"] = ""
os.environ["SUPABASE_SERVICE_ROLE_KEY"] = ""
os.environ["FLOPPI_WORKER_CREDENTIALS_JSON"] = "{}"
os.environ["APP_ENV"] = "test"
