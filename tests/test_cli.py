import json

from click.testing import CliRunner

from eda.cli.main import cli


def run(base_url, *args):
    runner = CliRunner()
    return runner.invoke(cli, ["--api-url", base_url, "--json", *args])


def test_cli_health(live_server):
    result = run(live_server, "health")
    assert result.exit_code == 0
    assert json.loads(result.output)["status"] == "UP"


def test_cli_template_and_activation_lifecycle(live_server):
    create = run(
        live_server, "template", "create",
        "--name", "vlan-activation", "--version", "1.0",
        "--step", "allocate_resources", "--step", "configure_ne",
    )
    assert create.exit_code == 0
    tpl = json.loads(create.output)
    tpl_id = tpl["id"]

    listing = run(live_server, "template", "list")
    assert tpl_id in listing.output

    act = run(
        live_server, "activation", "create",
        "--template", tpl_id, "--wait",
    )
    assert act.exit_code == 0
    assert "final state: ACTIVE" in act.output


def test_cli_ne_register_and_list(live_server):
    reg = run(
        live_server, "ne", "register",
        "--name", "core-router-1", "--type", "vrouter", "--ip", "10.0.0.5",
    )
    assert reg.exit_code == 0
    ne = json.loads(reg.output)
    assert ne["status"] == "REACHABLE"

    listing = run(live_server, "ne", "list")
    assert ne["id"] in listing.output


def test_cli_unknown_template_error_exit_code(live_server):
    result = run(live_server, "template", "show", "tpl-does-not-exist")
    assert result.exit_code == 1
