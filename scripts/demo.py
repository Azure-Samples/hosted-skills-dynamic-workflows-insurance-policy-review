"""Submit the sample request or download its generated report from local or Azure Storage."""

from __future__ import annotations

import argparse
import json
import os
from contextlib import suppress
from pathlib import Path
from typing import Any

from azure.core.exceptions import ResourceExistsError
from azure.identity import AzureDeveloperCliCredential
from azure.storage.blob import BlobServiceClient
from azure.storage.queue import QueueClient, TextBase64EncodePolicy

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REQUEST = ROOT / "examples" / "policy-service-request.json"
DEFAULT_OUTPUT = ROOT / "output" / "PSR-2026-00042.html"
DEFAULT_BLOB = "reviews/PSR-2026-00042.html"
DEFAULT_CONNECTION = "UseDevelopmentStorage=true"
QUEUE_NAME = "policy-service-requests"
DEFAULT_CONTAINER = "policy-review-packets"


def _connection_string() -> str:
    return os.environ.get("AzureWebJobsStorage", DEFAULT_CONNECTION)  # noqa: SIM112


def _container_name() -> str:
    return os.environ.get("POLICY_REVIEW_CONTAINER", DEFAULT_CONTAINER)


def _queue_name() -> str:
    return os.environ.get("POLICY_REQUEST_QUEUE", QUEUE_NAME)


def _queue_client() -> QueueClient:
    queue_name = _queue_name()
    queue_url = os.environ.get("POLICY_REVIEW_QUEUE_URL")
    if queue_url:
        return QueueClient(
            account_url=queue_url,
            queue_name=queue_name,
            credential=AzureDeveloperCliCredential(),
            message_encode_policy=TextBase64EncodePolicy(),
        )
    return QueueClient.from_connection_string(
        _connection_string(),
        queue_name,
        message_encode_policy=TextBase64EncodePolicy(),
    )


def _blob_service_client() -> BlobServiceClient:
    storage_url = os.environ.get("POLICY_REVIEW_STORAGE_URL")
    if storage_url:
        return BlobServiceClient(
            account_url=storage_url,
            credential=AzureDeveloperCliCredential(),
        )
    return BlobServiceClient.from_connection_string(_connection_string())


def _read_request(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain one JSON object")
    return value


def submit(request_path: Path) -> None:
    request = _read_request(request_path)
    queue = _queue_client()
    with suppress(ResourceExistsError):
        queue.create_queue()
    queue.send_message(json.dumps(request, separators=(",", ":")))

    documents = request.get("documents")
    document_count = len(documents) if isinstance(documents, list) else 0
    request_id = request.get("request_id", "unknown request")
    print(f"Submitted {request_id} with {document_count} documents.")
    print(f"Queue: {_queue_name()}")
    print(f"Blob destination: {_container_name()}/{request.get('review_blob', DEFAULT_BLOB)}")


def download(blob_name: str, output_path: Path) -> None:
    service = _blob_service_client()
    container_name = _container_name()
    blob = service.get_blob_client(container=container_name, blob=blob_name)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(blob.download_blob().readall())
    print(f"Downloaded {container_name}/{blob_name}")
    print(f"Output: {output_path.resolve()}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)

    submit_parser = subparsers.add_parser(
        "submit",
        help="Send a policy request to local or Azure Queue Storage.",
    )
    submit_parser.add_argument(
        "--request",
        type=Path,
        default=DEFAULT_REQUEST,
        help=f"Request JSON path. Default: {DEFAULT_REQUEST}",
    )

    download_parser = subparsers.add_parser(
        "download",
        help="Download the generated HTML review packet.",
    )
    download_parser.add_argument("--blob", default=DEFAULT_BLOB)
    download_parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser


def main() -> None:
    args = _parser().parse_args()
    if args.action == "submit":
        submit(args.request)
        return
    download(args.blob, args.output)


if __name__ == "__main__":
    main()
