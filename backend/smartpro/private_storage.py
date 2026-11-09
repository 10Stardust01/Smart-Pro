"""Private immutable S3-compatible storage for hosted document bytes.

Academic permissions remain in PostgreSQL; this layer never issues public URLs.
"""
import hashlib
import logging
import os
from uuid import UUID


logger = logging.getLogger(__name__)
MAX_BYTES = 2 * 1024 * 1024


def enabled():
    return os.getenv("SMARTPRO_STORAGE_BACKEND", "filesystem") == "s3"


def config_ready():
    return all(os.getenv(name) for name in (
        "SMARTPRO_S3_BUCKET",
        "SMARTPRO_S3_ENDPOINT_URL",
        "SMARTPRO_S3_ACCESS_KEY_ID",
        "SMARTPRO_S3_SECRET_ACCESS_KEY",
    ))


def _validate_key(key):
    if not isinstance(key, str) or not key.endswith(".pdf"):
        raise ValueError("Invalid private document key")
    try:
        UUID(key[:-4])
    except ValueError:
        raise ValueError("Invalid private document key") from None
    return key


def _client():
    # S3 is an optional hosted extra; local development must import without boto3.
    import boto3
    from botocore.config import Config

    if not config_ready():
        raise RuntimeError("S3 private storage is not configured")
    return boto3.client(
        "s3",
        endpoint_url=os.environ["SMARTPRO_S3_ENDPOINT_URL"],
        aws_access_key_id=os.environ["SMARTPRO_S3_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["SMARTPRO_S3_SECRET_ACCESS_KEY"],
        region_name=os.getenv("SMARTPRO_S3_REGION", "ap-southeast-1"),
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            connect_timeout=5,
            read_timeout=10,
            retries={"max_attempts": 2, "mode": "standard"},
        ),
    )


def read(key):
    """Read only a bounded private PDF; caller must authorize via SQL first."""
    from botocore.exceptions import BotoCoreError, ClientError
    key = _validate_key(key)
    try:
        response = _client().get_object(Bucket=os.environ["SMARTPRO_S3_BUCKET"], Key=key)
        body = response["Body"]
        try:
            content = body.read(MAX_BYTES + 1)
        finally:
            body.close()
    except (BotoCoreError, ClientError, OSError) as exc:
        logger.warning("private_document_read_failed kind=%s", type(exc).__name__)
        raise IOError("Private document could not be read") from None
    if len(content) > MAX_BYTES:
        raise IOError("Private document exceeds limit")
    return content


def put_immutable(key, content, expected_sha256):
    """Publish bytes once, never overwrite different bytes on retries."""
    from botocore.exceptions import BotoCoreError, ClientError
    key = _validate_key(key)
    if not isinstance(content, (bytes, bytearray)) or len(content) > MAX_BYTES:
        raise ValueError("Private PDF must be at most 2 MiB")
    if hashlib.sha256(content).hexdigest() != expected_sha256:
        raise ValueError("PDF digest mismatch")
    try:
        _client().put_object(
            Bucket=os.environ["SMARTPRO_S3_BUCKET"],
            Key=key,
            Body=bytes(content),
            ContentType="application/pdf",
            CacheControl="private, no-store",
            IfNoneMatch="*",
        )
        return
    except ClientError as exc:
        status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        code = exc.response.get("Error", {}).get("Code", "")
        if status not in (409, 412) and code not in ("PreconditionFailed", "ConditionalRequestConflict"):
            logger.warning("private_document_write_failed kind=ClientError")
            raise IOError("Private document could not be stored") from None
    except (BotoCoreError, OSError) as exc:
        logger.warning("private_document_write_failed kind=%s", type(exc).__name__)
        raise IOError("Private document could not be stored") from None

    existing = read(key)
    if len(existing) != len(content) or hashlib.sha256(existing).hexdigest() != expected_sha256:
        raise IOError("An existing document has different bytes")
