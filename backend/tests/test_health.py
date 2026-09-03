def test_health_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["razorpay_webhook_secured"] is True


def test_ready_probe(client):
    resp = client.get("/health/ready")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ready"


def test_openapi_schema_available(client):
    assert client.get("/openapi.json").status_code == 200


def test_security_headers_present(client):
    r = client.get("/health/ready")
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert r.headers.get("X-Frame-Options") == "DENY"
    assert "X-Request-ID" in r.headers
