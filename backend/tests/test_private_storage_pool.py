"""No-network regression tests for reusable per-process private S3 client."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import os
import sys
import threading
import time
from types import ModuleType, SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest

from smartpro import private_storage


@pytest.fixture
def fake_s3(monkeypatch):
    for key, value in {
        "SMARTPRO_S3_BUCKET": "synthetic-test-bucket",
        "SMARTPRO_S3_ENDPOINT_URL": "https://example.invalid",
        "SMARTPRO_S3_ACCESS_KEY_ID": "synthetic-access",
        "SMARTPRO_S3_SECRET_ACCESS_KEY": "synthetic-secret",
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(private_storage, "_cached_client", None)
    monkeypatch.setattr(private_storage, "_cached_client_pid", None)

    clients = []
    creations = []
    class FakeClient:
        def __init__(self):
            self.objects = {}
            self.put_calls = []

        def put_object(self, **kwargs):
            self.put_calls.append(kwargs)
            self.objects[kwargs["Key"]] = kwargs["Body"]

        def get_object(self, **kwargs):
            return {"Body": io.BytesIO(self.objects[kwargs["Key"]])}

    class FakeSession:
        def __init__(self):
            creations.append("session")
            # Make races observable; concurrent initial callers must not each
            # create a default session/client independently.
            time.sleep(.02)

        def client(self, service, **kwargs):
            assert service == "s3"
            assert kwargs["endpoint_url"] == "https://example.invalid"
            assert kwargs["config"]["signature_version"] == "s3v4"
            client = FakeClient()
            clients.append(client)
            return client

    boto3 = ModuleType("boto3")
    boto3.session = SimpleNamespace(Session=FakeSession)
    botocore = ModuleType("botocore")
    config = ModuleType("botocore.config")
    config.Config = lambda **kwargs: kwargs
    exceptions = ModuleType("botocore.exceptions")
    exceptions.BotoCoreError = type("BotoCoreError", (Exception,), {})
    exceptions.ClientError = type("ClientError", (Exception,), {})
    monkeypatch.setitem(sys.modules, "boto3", boto3)
    monkeypatch.setitem(sys.modules, "botocore", botocore)
    monkeypatch.setitem(sys.modules, "botocore.config", config)
    monkeypatch.setitem(sys.modules, "botocore.exceptions", exceptions)
    return creations, clients


def test_first_concurrent_requests_share_one_client_and_pool(fake_s3):
    creations, clients = fake_s3
    barrier = threading.Barrier(8)
    def get_client():
        barrier.wait(timeout=5)
        return private_storage._client()
    with ThreadPoolExecutor(max_workers=8) as pool:
        handles = list(pool.map(lambda _i: get_client(), range(8)))
    assert len(creations) == 1
    assert len(clients) == 1
    assert all(handle is clients[0] for handle in handles)


def test_client_is_recreated_after_worker_process_changes(fake_s3):
    creations, clients = fake_s3
    # No actual fork or shared networking needed to exercise PID guard.
    with patch.object(private_storage.os, "getpid", return_value=314):
        first = private_storage._client()
    with patch.object(private_storage.os, "getpid", return_value=315):
        second = private_storage._client()
    assert first is not second
    assert len(creations) == len(clients) == 2


def test_immutable_put_and_read_share_client_without_public_urls(fake_s3):
    _, clients = fake_s3
    key = str(uuid4()) + ".pdf"
    content = b"%PDF-1.4\n%%EOF\n"
    digest = hashlib.sha256(content).hexdigest()
    private_storage.put_immutable(key, content, digest)
    assert private_storage.read(key) == content
    assert len(clients) == 1
    assert clients[0].put_calls[0]["IfNoneMatch"] == "*"
    assert clients[0].put_calls[0]["CacheControl"] == "private, no-store"


def test_missing_staging_storage_configuration_fails_closed(fake_s3, monkeypatch):
    monkeypatch.delenv("SMARTPRO_S3_BUCKET")
    with pytest.raises(RuntimeError, match="not configured"):
        private_storage._client()
