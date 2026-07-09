"""
Tests for the second round of features, added after comparing this
project against the real Ericsson EDA architecture document:
target mutex, NE blocking/HELD activations, auto-retry, webhooks,
batch creation, alarms, Prometheus metrics and API-key auth.
"""
import threading
import time

import pytest
from fastapi.testclient import TestClient

from eda.api.main import app
from eda.config import settings
from eda.core.engine import ActivationEngine
from eda.core.store import get_store

client = TestClient(app)


def _make_template(steps=None):
    resp = client.post(
        "/templates",
        json={"name": "t", "version": "1.0", "steps": steps or ["a", "b"]},
    )
    assert resp.status_code == 201
    return resp.json()


# --------------------------------------------------------------------- #
# Target mutex (Mutex Handler equivalent)
# --------------------------------------------------------------------- #
def test_concurrent_activation_on_same_target_is_rejected():
    tpl = _make_template(steps=["a", "b", "c"])
    store = get_store()
    engine = ActivationEngine(store)

    act1 = store.create_activation(template_id=tpl["id"], ne_id=None, params={})
    assert store.try_acquire_target("self")
    t = threading.Thread(target=engine.run_activation, args=(act1.id,))
    t.start()
    time.sleep(0.05)  # let the workflow get underway while target is busy

    resp = client.post("/activations", json={"template_id": tpl["id"]})
    assert resp.status_code == 409
    assert "busy" in resp.json()["detail"]

    t.join(timeout=10)
    # target released once the first activation finished
    assert not store.is_target_busy("self")


def test_different_targets_do_not_block_each_other():
    tpl = _make_template()
    ne1 = client.post(
        "/network-elements", json={"name": "ne1", "management_ip": "10.0.0.1"}
    ).json()
    ne2 = client.post(
        "/network-elements", json={"name": "ne2", "management_ip": "10.0.0.2"}
    ).json()
    r1 = client.post("/activations", json={"template_id": tpl["id"], "ne_id": ne1["id"]})
    r2 = client.post("/activations", json={"template_id": tpl["id"], "ne_id": ne2["id"]})
    assert r1.status_code == 202
    assert r2.status_code == 202


# --------------------------------------------------------------------- #
# NE blocking / HELD activations (CUDB Activation Blocker equivalent)
# --------------------------------------------------------------------- #
def test_activation_on_blocked_ne_is_held_then_resumed_on_unblock():
    tpl = _make_template()
    ne = client.post(
        "/network-elements", json={"name": "ne-block", "management_ip": "10.0.0.9"}
    ).json()

    block_resp = client.post(f"/network-elements/{ne['id']}/block")
    assert block_resp.status_code == 200
    assert block_resp.json()["blocked"] is True

    act = client.post(
        "/activations", json={"template_id": tpl["id"], "ne_id": ne["id"], "params": {}}
    ).json()
    assert act["state"] == "HELD"

    unblock_resp = client.post(f"/network-elements/{ne['id']}/unblock")
    assert unblock_resp.status_code == 200
    assert unblock_resp.json()["blocked"] is False

    final = client.get(f"/activations/{act['id']}").json()
    assert final["state"] == "ACTIVE"


# --------------------------------------------------------------------- #
# Auto-retry (Activation Replicator equivalent) + alarms (Alarm Handler)
# --------------------------------------------------------------------- #
def test_auto_retry_exhausts_and_raises_alarm():
    tpl = _make_template(steps=["a", "b"])
    act = client.post(
        "/activations",
        json={
            "template_id": tpl["id"],
            "params": {
                "fail_at_step": "b",
                "auto_retry": {"max_attempts": 3, "backoff_seconds": 0.05},
            },
        },
    ).json()

    final = client.get(f"/activations/{act['id']}").json()
    assert final["state"] == "FAILED"
    assert final["attempts"] == 3

    alarms = client.get("/alarms", params={"active": True}).json()
    assert any(a["source"] == "self" and act["id"] in a["text"] for a in alarms)


def test_alarm_clear():
    tpl = _make_template(steps=["a"])
    act = client.post(
        "/activations", json={"template_id": tpl["id"], "params": {"fail_at_step": "a"}}
    ).json()
    alarms = client.get("/alarms", params={"active": True}).json()
    mine = [a for a in alarms if act["id"] in a["text"]]
    assert mine
    alarm_id = mine[0]["id"]
    resp = client.post(f"/alarms/{alarm_id}/clear")
    assert resp.status_code == 200
    assert resp.json()["cleared_at"] is not None


# --------------------------------------------------------------------- #
# Webhook notification (Inbound Async equivalent)
# --------------------------------------------------------------------- #
def test_webhook_is_called_on_terminal_state(monkeypatch):
    calls = []

    def fake_post(url, json=None, timeout=None):
        calls.append((url, json))

        class _Resp:
            status_code = 200

        return _Resp()

    monkeypatch.setattr("eda.core.engine.requests.post", fake_post)

    tpl = _make_template(steps=["a"])
    act = client.post(
        "/activations",
        json={"template_id": tpl["id"], "params": {"webhook_url": "http://example.invalid/hook"}},
    ).json()

    assert len(calls) == 1
    assert calls[0][0] == "http://example.invalid/hook"
    assert calls[0][1]["id"] == act["id"]
    assert calls[0][1]["state"] == "ACTIVE"


# --------------------------------------------------------------------- #
# Batch creation (Inbound Batch Handler equivalent)
# --------------------------------------------------------------------- #
def test_batch_partial_success():
    tpl = _make_template()
    resp = client.post(
        "/activations/batch",
        json={"activations": [{"template_id": tpl["id"]}, {"template_id": "does-not-exist"}]},
    )
    assert resp.status_code == 200
    results = resp.json()
    assert results[0]["ok"] is True
    assert results[0]["activation"]["state"] in ("ACTIVE", "VALIDATING", "ACTIVATING", "CREATED")
    assert results[1]["ok"] is False
    assert "does-not-exist" in results[1]["error"]


# --------------------------------------------------------------------- #
# Prometheus metrics (PM Server equivalent)
# --------------------------------------------------------------------- #
def test_metrics_endpoint_exposes_known_series():
    tpl = _make_template()
    client.post("/activations", json={"template_id": tpl["id"]})
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "eda_activations_created_total" in resp.text
    assert "eda_activation_duration_seconds" in resp.text


# --------------------------------------------------------------------- #
# API-key auth (AAA equivalent)
# --------------------------------------------------------------------- #
def test_api_key_enforced_when_configured(monkeypatch):
    monkeypatch.setattr(settings, "API_KEY", "s3cret")
    try:
        assert client.get("/templates").status_code == 401
        assert client.get("/templates", headers={"X-API-Key": "wrong"}).status_code == 401
        assert client.get("/templates", headers={"X-API-Key": "s3cret"}).status_code == 200
        # Health and metrics stay open regardless of API key configuration.
        assert client.get("/health").status_code == 200
        assert client.get("/metrics").status_code == 200
    finally:
        monkeypatch.setattr(settings, "API_KEY", "")


def test_no_api_key_required_by_default():
    assert settings.API_KEY == ""
    assert client.get("/templates").status_code == 200
