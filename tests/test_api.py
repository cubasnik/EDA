import pytest
from fastapi.testclient import TestClient

from eda.api.main import app

client = TestClient(app)


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "UP"


def test_version():
    resp = client.get("/version")
    assert resp.status_code == 200
    assert "EDA" in resp.json()["product"]


def test_template_crud():
    resp = client.post(
        "/templates",
        json={
            "name": "vlan-activation",
            "version": "1.0",
            "description": "Activate a VLAN service",
            "steps": ["allocate_resources", "configure_ne", "verify_activation"],
        },
    )
    assert resp.status_code == 201
    tpl = resp.json()
    tpl_id = tpl["id"]

    resp = client.get("/templates")
    assert resp.status_code == 200
    assert any(t["id"] == tpl_id for t in resp.json())

    resp = client.get(f"/templates/{tpl_id}")
    assert resp.status_code == 200

    resp = client.delete(f"/templates/{tpl_id}")
    assert resp.status_code == 204

    resp = client.get(f"/templates/{tpl_id}")
    assert resp.status_code == 404


def test_network_element_crud():
    resp = client.post(
        "/network-elements",
        json={"name": "core-router-1", "ne_type": "vrouter", "management_ip": "10.0.0.5"},
    )
    assert resp.status_code == 201
    ne_id = resp.json()["id"]

    resp = client.get(f"/network-elements/{ne_id}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "REACHABLE"

    resp = client.delete(f"/network-elements/{ne_id}")
    assert resp.status_code == 204


def test_activation_full_lifecycle():
    tpl_resp = client.post(
        "/templates",
        json={
            "name": "qos-activation",
            "version": "1.0",
            "description": "Activate QoS profile",
            "steps": ["allocate_resources", "configure_ne"],
        },
    )
    tpl_id = tpl_resp.json()["id"]

    act_resp = client.post("/activations", json={"template_id": tpl_id, "params": {}})
    assert act_resp.status_code == 202
    act_id = act_resp.json()["id"]

    status_resp = client.get(f"/activations/{act_id}/status")
    assert status_resp.status_code == 200
    assert status_resp.json()["state"] == "ACTIVE"

    logs_resp = client.get(f"/activations/{act_id}/logs")
    assert logs_resp.status_code == 200
    assert len(logs_resp.json()["logs"]) > 0

    deact_resp = client.post(f"/activations/{act_id}/deactivate")
    assert deact_resp.status_code == 202

    final = client.get(f"/activations/{act_id}").json()
    assert final["state"] == "DEACTIVATED"


def test_activation_with_injected_failure_and_retry():
    tpl_resp = client.post(
        "/templates",
        json={"name": "apn-activation", "version": "1.0", "steps": ["configure_ne"]},
    )
    tpl_id = tpl_resp.json()["id"]

    act_resp = client.post(
        "/activations",
        json={"template_id": tpl_id, "params": {"fail_at_step": "configure_ne"}},
    )
    act_id = act_resp.json()["id"]

    assert client.get(f"/activations/{act_id}").json()["state"] == "FAILED"

    retry_resp = client.post(f"/activations/{act_id}/retry")
    assert retry_resp.status_code == 202
    # still fails since params still contain fail_at_step
    assert client.get(f"/activations/{act_id}").json()["state"] == "FAILED"


def test_create_activation_unknown_template_returns_404():
    resp = client.post("/activations", json={"template_id": "tpl-nope", "params": {}})
    assert resp.status_code == 404


def test_deactivate_created_activation_conflict():
    tpl_resp = client.post(
        "/templates", json={"name": "slow-tpl", "version": "1.0", "steps": []}
    )
    tpl_id = tpl_resp.json()["id"]
    act_resp = client.post("/activations", json={"template_id": tpl_id, "params": {}})
    act_id = act_resp.json()["id"]
    # By the time the background task ran, template with no steps goes straight to ACTIVE,
    # so deactivating twice in a row should eventually 409 once DEACTIVATED.
    client.post(f"/activations/{act_id}/deactivate")
    resp = client.post(f"/activations/{act_id}/deactivate")
    assert resp.status_code == 409
