from eda.core.engine import ActivationEngine
from eda.core.models import ActivationState
from eda.core.store import Store


def make_store(tmp_path):
    return Store(str(tmp_path / "engine-test.db"))


def test_successful_activation_reaches_active(tmp_path):
    store = make_store(tmp_path)
    engine = ActivationEngine(store)

    tpl = store.create_template(
        name="vlan-activation", version="1.0", description="test",
        steps=["allocate_resources", "configure_ne", "verify_activation"],
    )
    act = store.create_activation(template_id=tpl.id, ne_id=None, params={})

    engine.run_activation(act.id)

    result = store.get_activation(act.id)
    assert result.state == ActivationState.ACTIVE
    assert result.error is None
    assert result.current_step is None

    logs = store.get_logs(act.id)
    assert any("Activation completed successfully" in l["message"] for l in logs)


def test_activation_fails_at_injected_step(tmp_path):
    store = make_store(tmp_path)
    engine = ActivationEngine(store)

    tpl = store.create_template(
        name="vlan-activation", version="1.0", description="test",
        steps=["allocate_resources", "configure_ne", "verify_activation"],
    )
    act = store.create_activation(
        template_id=tpl.id, ne_id=None, params={"fail_at_step": "configure_ne"}
    )

    engine.run_activation(act.id)

    result = store.get_activation(act.id)
    assert result.state == ActivationState.FAILED
    assert "configure_ne" in result.error


def test_activation_missing_template_fails_immediately(tmp_path):
    store = make_store(tmp_path)
    engine = ActivationEngine(store)

    act = store.create_activation(template_id="tpl-does-not-exist", ne_id=None, params={})
    engine.run_activation(act.id)

    result = store.get_activation(act.id)
    assert result.state == ActivationState.FAILED
    assert "not found" in result.error


def test_deactivate_then_retry_cycle(tmp_path):
    store = make_store(tmp_path)
    engine = ActivationEngine(store)

    tpl = store.create_template(
        name="vlan-activation", version="1.0", description="test", steps=["configure_ne"]
    )
    act = store.create_activation(template_id=tpl.id, ne_id=None, params={})
    engine.run_activation(act.id)
    assert store.get_activation(act.id).state == ActivationState.ACTIVE

    engine.run_deactivation(act.id)
    assert store.get_activation(act.id).state == ActivationState.DEACTIVATED

    # A deactivated activation cannot be retried (retry only applies to FAILED)
    engine.retry_activation(act.id)
    assert store.get_activation(act.id).state == ActivationState.DEACTIVATED


def test_retry_recovers_failed_activation(tmp_path):
    store = make_store(tmp_path)
    engine = ActivationEngine(store)

    tpl = store.create_template(
        name="vlan-activation", version="1.0", description="test",
        steps=["allocate_resources", "configure_ne"],
    )
    act = store.create_activation(
        template_id=tpl.id, ne_id=None, params={"fail_at_step": "configure_ne"}
    )
    engine.run_activation(act.id)
    assert store.get_activation(act.id).state == ActivationState.FAILED

    # Clear the injected failure and retry - should now succeed
    store.update_activation(act.id, error=None, clear_error=True)
    act_row = store.get_activation(act.id)
    act_row.params.pop("fail_at_step", None)
    store._conn.execute(  # simulate an operator editing params before retry
        "UPDATE activations SET params = ? WHERE id = ?",
        ("{}", act.id),
    )
    store._conn.commit()

    engine.retry_activation(act.id)
    assert store.get_activation(act.id).state == ActivationState.ACTIVE
