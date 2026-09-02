from __future__ import annotations

import pytest
from scripts import demo


def test_cloud_clients_use_azd_identity_and_azd_outputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    credential = object()
    queue_clients: list[dict[str, object]] = []
    blob_clients: list[dict[str, object]] = []

    class FakeQueueClient:
        def __init__(self, **kwargs: object) -> None:
            queue_clients.append(kwargs)

    class FakeBlobServiceClient:
        def __init__(self, **kwargs: object) -> None:
            blob_clients.append(kwargs)

    monkeypatch.setenv(
        "POLICY_REVIEW_QUEUE_URL",
        "https://sample.queue.core.windows.net/",
    )
    monkeypatch.setenv("POLICY_REQUEST_QUEUE", "requests")
    monkeypatch.setenv(
        "POLICY_REVIEW_STORAGE_URL",
        "https://sample.blob.core.windows.net/",
    )
    monkeypatch.setattr(demo, "AzureDeveloperCliCredential", lambda: credential)
    monkeypatch.setattr(demo, "QueueClient", FakeQueueClient)
    monkeypatch.setattr(demo, "BlobServiceClient", FakeBlobServiceClient)

    demo._queue_client()
    demo._blob_service_client()

    assert len(queue_clients) == 1
    assert queue_clients[0]["account_url"] == "https://sample.queue.core.windows.net/"
    assert queue_clients[0]["queue_name"] == "requests"
    assert queue_clients[0]["credential"] is credential
    assert isinstance(
        queue_clients[0]["message_encode_policy"],
        demo.TextBase64EncodePolicy,
    )
    assert blob_clients == [
        {
            "account_url": "https://sample.blob.core.windows.net/",
            "credential": credential,
        }
    ]
