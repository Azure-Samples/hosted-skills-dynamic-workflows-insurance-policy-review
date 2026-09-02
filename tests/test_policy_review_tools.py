from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from tools import policy_review_tools
from tools.policy_review_tools import (
    build_policy_review_packet,
    inspect_policy_document,
    load_policy_context,
    publish_policy_review_packet,
    render_policy_review_html,
    validate_policy_service_request,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def sample_request() -> dict[str, Any]:
    return json.loads(
        (ROOT / "examples" / "policy-service-request.json").read_text(encoding="utf-8")
    )


def test_validate_request_normalizes_and_bounds_documents(
    sample_request: dict[str, Any],
) -> None:
    result = validate_policy_service_request({"request": sample_request})

    assert result["request_id"] == "PSR-2026-00042"
    assert result["policy_id"] == "AUTO-100042"
    assert result["review_blob"] == "reviews/PSR-2026-00042.html"
    assert [document["in_scope"] for document in result["documents"]] == [
        True,
        True,
        True,
        False,
    ]

    too_many = copy.deepcopy(sample_request)
    too_many["documents"] = [
        {
            "document_id": f"DOC-{index:03}",
            "kind": "signed_request",
            "file_name": f"document-{index}.pdf",
            "status": "received",
        }
        for index in range(9)
    ]
    with pytest.raises(ValueError, match="at most 8 documents"):
        validate_policy_service_request({"request": too_many})


def test_validate_request_allows_no_documents_for_missing_evidence_packet(
    sample_request: dict[str, Any],
) -> None:
    sample_request["documents"] = []

    result = validate_policy_service_request({"request": sample_request})

    assert result["documents"] == []


def test_policy_context_is_deterministic_and_decision_neutral() -> None:
    args = {
        "policy_id": "AUTO-100042",
        "requested_change_type": "add_driver",
    }

    first = load_policy_context(args)
    second = load_policy_context(args)

    assert first == second
    assert first["found"] is True
    assert first["review_requirements"]["required_documents"] == [
        "driver_license",
        "signed_request",
    ]
    assert "decision" not in first
    assert "eligibility" not in first


def test_document_inspection_reports_evidence_without_deciding(
    sample_request: dict[str, Any],
) -> None:
    normalized = validate_policy_service_request({"request": sample_request})

    present = inspect_policy_document(
        {
            "request_id": normalized["request_id"],
            "position": 0,
            "document": normalized["documents"][0],
        }
    )
    missing = inspect_policy_document(
        {
            "request_id": normalized["request_id"],
            "position": 2,
            "document": normalized["documents"][2],
        }
    )

    assert present["evidence_state"] == "present"
    assert present["requires_manual_verification"] is True
    assert missing["evidence_state"] == "missing"
    assert present.get("decision") is None
    assert missing.get("decision") is None


def test_review_packet_consumes_ordered_fan_in_and_requires_human_decision(
    sample_request: dict[str, Any],
) -> None:
    request = validate_policy_service_request({"request": sample_request})
    policy = load_policy_context(
        {
            "policy_id": request["policy_id"],
            "requested_change_type": request["requested_change"]["type"],
        }
    )
    checks = [
        (
            {
                "index": index,
                "status": "completed",
                "result": inspect_policy_document(
                    {
                        "request_id": request["request_id"],
                        "position": index,
                        "document": document,
                    }
                ),
            }
            if document["in_scope"]
            else {"index": index, "status": "skipped", "result": None}
        )
        for index, document in enumerate(request["documents"])
    ]

    packet = build_policy_review_packet(
        {
            "request": request,
            "policy": policy,
            "document_checks": checks,
        }
    )

    assert packet["review_status"] == "human_review_required"
    assert packet["decision"] is None
    assert packet["decision_authority"] == "human_policy_reviewer"
    assert packet["automation_scope"] == "evidence_collection_and_packet_preparation_only"
    assert packet["document_summary"] == {
        "submitted": 4,
        "inspected": 3,
        "skipped": 1,
        "present": 2,
        "missing_or_follow_up": 1,
    }
    assert packet["document_checks"][0]["document_id"] == "DOC-001"
    assert packet["document_checks"][2]["document_id"] == "DOC-003"
    assert packet["excluded_documents"] == [
        {
            "document_id": "DOC-004",
            "kind": "customer_note",
            "reason": "not included in this sample's bounded review scope",
        }
    ]
    assert any("proof_of_residency" in item for item in packet["missing_information"])


def test_review_packet_uses_envelope_indexes_and_surfaces_superseded_evidence(
    sample_request: dict[str, Any],
) -> None:
    sample_request["documents"] = [
        {
            "document_id": "DOC-OLD",
            "kind": "driver_license",
            "file_name": "expired-license.pdf",
            "status": "expired",
        },
        {
            "document_id": "DOC-NEW",
            "kind": "driver_license",
            "file_name": "current-license.pdf",
            "status": "received",
        },
        {
            "document_id": "DOC-SIGNED",
            "kind": "signed_request",
            "file_name": "signed-request.pdf",
            "status": "received",
        },
    ]
    request = validate_policy_service_request({"request": sample_request})
    policy = load_policy_context(
        {
            "policy_id": request["policy_id"],
            "requested_change_type": request["requested_change"]["type"],
        }
    )
    checks = [
        {
            "index": index,
            "status": "completed",
            "result": inspect_policy_document(
                {
                    "request_id": request["request_id"],
                    "document": document,
                }
            ),
        }
        for index, document in enumerate(request["documents"])
    ]

    packet = build_policy_review_packet(
        {
            "request": request,
            "policy": policy,
            "document_checks": checks,
        }
    )

    assert [result["position"] for result in packet["document_checks"]] == [0, 1, 2]
    assert any("DOC-OLD" in item for item in packet["missing_information"])


def test_unknown_change_type_is_flagged_for_authoritative_review(
    sample_request: dict[str, Any],
) -> None:
    sample_request["requested_change"]["type"] = "cancel_policy"
    sample_request["documents"] = [
        {
            "document_id": "DOC-001",
            "kind": "signed_request",
            "file_name": "signed-request.pdf",
            "status": "received",
        }
    ]
    request = validate_policy_service_request({"request": sample_request})
    policy = load_policy_context(
        {
            "policy_id": request["policy_id"],
            "requested_change_type": request["requested_change"]["type"],
        }
    )
    check = inspect_policy_document(
        {
            "request_id": request["request_id"],
            "document": request["documents"][0],
        }
    )

    packet = build_policy_review_packet(
        {
            "request": request,
            "policy": policy,
            "document_checks": [{"index": 0, "status": "completed", "result": check}],
        }
    )

    assert policy["change_type_recognized"] is False
    assert any("cancel_policy" in item for item in packet["missing_information"])


def test_html_renderer_escapes_values_and_emphasizes_human_review(
    sample_request: dict[str, Any],
) -> None:
    request = validate_policy_service_request({"request": sample_request})
    policy = load_policy_context(
        {
            "policy_id": request["policy_id"],
            "requested_change_type": request["requested_change"]["type"],
        }
    )
    policy["policy"]["named_insured"] = "Taylor <Morgan>"
    packet = build_policy_review_packet(
        {
            "request": request,
            "policy": policy,
            "document_checks": [
                {
                    "index": index,
                    "status": "completed",
                    "result": inspect_policy_document(
                        {
                            "request_id": request["request_id"],
                            "position": index,
                            "document": document,
                        }
                    ),
                }
                for index, document in enumerate(request["documents"][:3])
            ],
        }
    )

    result = render_policy_review_html({"packet": packet})

    assert result["request_id"] == "PSR-2026-00042"
    assert result["review_status"] == "human_review_required"
    assert "Taylor &lt;Morgan&gt;" in result["html"]
    assert "Taylor <Morgan>" not in result["html"]
    assert "Human review required" in result["html"]
    assert "No policy decision has been made" in result["html"]


def test_blob_publisher_overwrites_stable_destination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uploads: list[tuple[str, bytes, bool, str]] = []

    class FakeBlob:
        def __init__(self, name: str) -> None:
            self.name = name

        def upload_blob(
            self,
            data: bytes,
            *,
            overwrite: bool,
            content_settings: Any,
        ) -> None:
            uploads.append((self.name, data, overwrite, content_settings.content_type))

    class FakeContainer:
        def create_container(self) -> None:
            return None

        def get_blob_client(self, name: str) -> FakeBlob:
            return FakeBlob(name)

    class FakeService:
        def get_container_client(self, name: str) -> FakeContainer:
            assert name == "test-policy-reviews"
            return FakeContainer()

    monkeypatch.setenv("AzureWebJobsStorage", "UseDevelopmentStorage=true")
    monkeypatch.setenv("POLICY_REVIEW_CONTAINER", "test-policy-reviews")
    monkeypatch.setattr(
        "tools.policy_review_tools.BlobServiceClient.from_connection_string",
        lambda _value: FakeService(),
    )

    result = publish_policy_review_packet(
        {
            "report": {
                "html": "<html>review</html>",
                "request_id": "PSR-2026-00042",
                "review_status": "human_review_required",
                "decision": None,
            },
            "blob_name": "reviews/PSR-2026-00042.html",
        }
    )

    assert uploads == [
        (
            "reviews/PSR-2026-00042.html",
            b"<html>review</html>",
            True,
            "text/html; charset=utf-8",
        )
    ]
    assert result == {
        "event": "policy_review_packet_published",
        "container": "test-policy-reviews",
        "blob_name": "reviews/PSR-2026-00042.html",
        "request_id": "PSR-2026-00042",
        "review_status": "human_review_required",
        "decision": None,
    }


def test_blob_publisher_uses_managed_identity_in_azure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[tuple[str, object]] = []
    uploads: list[bytes] = []
    credential = object()

    class FakeBlob:
        def upload_blob(
            self,
            data: bytes,
            *,
            overwrite: bool,
            content_settings: Any,
        ) -> None:
            assert overwrite is True
            assert content_settings.content_type == "text/html; charset=utf-8"
            uploads.append(data)

    class FakeContainer:
        def create_container(self) -> None:
            return None

        def get_blob_client(self, name: str) -> FakeBlob:
            assert name == "reviews/PSR-2026-00042.html"
            return FakeBlob()

    class FakeBlobServiceClient:
        def __init__(self, account_url: str, credential: object) -> None:
            created.append((account_url, credential))

        def get_container_client(self, name: str) -> FakeContainer:
            assert name == "policy-review-packets"
            return FakeContainer()

    monkeypatch.delenv("AzureWebJobsStorage", raising=False)
    monkeypatch.setenv(
        "POLICY_REVIEW_STORAGE_URL",
        "https://sample.blob.core.windows.net/",
    )
    monkeypatch.setenv("AZURE_CLIENT_ID", "00000000-0000-0000-0000-000000000001")
    monkeypatch.setattr(policy_review_tools, "BlobServiceClient", FakeBlobServiceClient)
    monkeypatch.setattr(
        policy_review_tools,
        "DefaultAzureCredential",
        lambda *, managed_identity_client_id: credential,
        raising=False,
    )

    result = publish_policy_review_packet(
        {
            "report": {
                "html": "<html>review</html>",
                "request_id": "PSR-2026-00042",
                "review_status": "human_review_required",
                "decision": None,
            },
            "blob_name": "reviews/PSR-2026-00042.html",
        }
    )

    assert created == [("https://sample.blob.core.windows.net/", credential)]
    assert uploads == [b"<html>review</html>"]
    assert result["container"] == "policy-review-packets"
