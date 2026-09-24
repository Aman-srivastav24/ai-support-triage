"""Document upload: RBAC, deduplication, and background ingestion.

The ingestion test is the proof that the embedder override reaches the
background task, which opens its own database session and runs after the
response has been written.
"""

DOC_TEXT = (
    "Refunds are available within 14 days of the first charge on a new "
    "subscription. Renewal charges are not refundable."
)


def upload(client, headers, text: str = DOC_TEXT, filename: str = "refunds.txt"):
    return client.post(
        "/documents",
        headers=headers,
        files={"file": (filename, text.encode("utf-8"), "text/plain")},
        data={"title": "Refund policy"},
    )


def test_admin_upload_is_accepted_then_ingested_with_the_fake_embedder(
    client, admin_headers, fake_embedder
):
    response = upload(client, admin_headers)

    # The receipt is written BEFORE the background task runs, so it
    # truthfully says pending even though ingestion has finished by now.
    assert response.status_code == 202
    receipt = response.json()
    assert receipt["status"] == "pending"
    assert receipt["chunk_count"] == 0

    # TestClient runs background tasks before returning, so ingestion is done.
    document = client.get(f"/documents/{receipt['id']}", headers=admin_headers).json()
    assert document["status"] == "ready", document["error_message"]
    assert document["chunk_count"] >= 1

    # One embedding per chunk, all as documents, all through the fake.
    assert len(fake_embedder.calls) == document["chunk_count"]
    assert all(task == "RETRIEVAL_DOCUMENT" for _, task in fake_embedder.calls)


def test_an_agent_cannot_upload(client, agent_headers, fake_embedder):
    response = upload(client, agent_headers)

    assert response.status_code == 403
    assert fake_embedder.calls == []


def test_upload_requires_a_token(client):
    response = upload(client, headers={})

    assert response.status_code == 401


def test_identical_content_is_rejected_as_a_duplicate(client, admin_headers):
    upload(client, admin_headers)

    # Different filename, same bytes: dedup is by content hash, not name.
    response = upload(client, admin_headers, filename="copy-of-refunds.txt")

    assert response.status_code == 409