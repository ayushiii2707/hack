def test_health_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"


def test_openapi_schema_available(client):
    assert client.get("/openapi.json").status_code == 200
