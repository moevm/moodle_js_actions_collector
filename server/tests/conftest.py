import os


# Non-secret defaults for isolated tests. Container configuration, when present,
# takes precedence; API tests override the actual authentication dependencies.
os.environ.setdefault("COLLECTOR_AUTH_SECRET", "test-signing-secret-" + "a" * 40)
os.environ.setdefault("COLLECTOR_INGEST_KEY", "test-ingestion-key-" + "b" * 40)
