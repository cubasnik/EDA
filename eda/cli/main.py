"""
eda-cli - command line client for the EDA (Enhanced Dynamic Activation)
virtual network element. It is a thin client on top of the REST API,
so anything the CLI can do, any northbound OSS/BSS system can do too.
"""
from __future__ import annotations

import json
import os
import sys
import time
from typing import Any, Optional

import click
from tabulate import tabulate

from eda import __version__
from eda.cli.client import ApiClient, ApiError
from eda.config import settings

TERMINAL_STATES = {"ACTIVE", "FAILED", "DEACTIVATED"}


class Context:
    def __init__(self, api_url: str, api_key: str, as_json: bool):
        self.client = ApiClient(api_url, api_key=api_key)
        self.as_json = as_json


pass_ctx = click.make_pass_decorator(Context)


def _print(ctx: Context, data: Any, headers: Optional[list] = None) -> None:
    if ctx.as_json:
        click.echo(json.dumps(data, indent=2, ensure_ascii=False))
        return
    if isinstance(data, list):
        if not data:
            click.echo("(no results)")
            return
        rows = [list(item.values()) for item in data]
        cols = headers or list(data[0].keys())
        click.echo(tabulate(rows, headers=cols, tablefmt="simple"))
    elif isinstance(data, dict):
        rows = [[k, v] for k, v in data.items()]
        click.echo(tabulate(rows, tablefmt="simple"))
    else:
        click.echo(str(data))


def _fail(exc: ApiError) -> None:
    prefix = f"[HTTP {exc.status_code}] " if exc.status_code else ""
    click.secho(f"Error: {prefix}{exc.detail}", fg="red", err=True)
    sys.exit(1)


def _load_json_arg(value: Optional[str], file: Optional[str]) -> dict:
    if file:
        with open(file, "r", encoding="utf-8") as fh:
            return json.load(fh)
    if value:
        return json.loads(value)
    return {}


# ------------------------------------------------------------------ #
# Top-level group
# ------------------------------------------------------------------ #
@click.group()
@click.option(
    "--api-url", "-u", default=settings.API_URL, show_default=True,
    help="Base URL of the EDA REST API (env: EDA_API_URL)",
)
@click.option(
    "--api-key", "-k", default=lambda: os.environ.get("EDA_API_KEY", ""),
    help="API key sent as X-API-Key (env: EDA_API_KEY). Only needed if the "
    "server was started with EDA_API_KEY set.",
)
@click.option("--json", "as_json", is_flag=True, help="Output raw JSON instead of tables")
@click.version_option(version=__version__, prog_name="eda-cli")
@click.pass_context
def cli(click_ctx: click.Context, api_url: str, api_key: str, as_json: bool):
    """EDA (Enhanced Dynamic Activation) - virtual network element CLI."""
    click_ctx.obj = Context(api_url=api_url, api_key=api_key, as_json=as_json)


@cli.command()
@pass_ctx
def health(ctx: Context):
    """Check the health of the EDA network element."""
    try:
        _print(ctx, ctx.client.get("/health"))
    except ApiError as exc:
        _fail(exc)


@cli.command()
@pass_ctx
def version(ctx: Context):
    """Show EDA product/version info reported by the network element."""
    try:
        _print(ctx, ctx.client.get("/version"))
    except ApiError as exc:
        _fail(exc)


# ------------------------------------------------------------------ #
# template group
# ------------------------------------------------------------------ #
@cli.group()
def template():
    """Manage service activation templates."""


@template.command("create")
@click.option("--name", default=None, help="Required unless --file is given")
@click.option("--version", "tpl_version", default="1.0", show_default=True)
@click.option("--description", default="")
@click.option(
    "--step", "steps", multiple=True,
    help="Activation step name, repeatable, e.g. --step configure_vlan --step verify",
)
@click.option("--file", "file_path", type=click.Path(exists=True), help="Load full template JSON from file")
@pass_ctx
def template_create(ctx: Context, name, tpl_version, description, steps, file_path):
    """Create a new service template (either via flags or --file with full JSON)."""
    if not file_path and not name:
        raise click.UsageError("Either --name or --file must be provided")
    try:
        if file_path:
            with open(file_path, "r", encoding="utf-8") as fh:
                body = json.load(fh)
        else:
            body = {
                "name": name,
                "version": tpl_version,
                "description": description,
                "steps": list(steps),
            }
        _print(ctx, ctx.client.post("/templates", body))
    except ApiError as exc:
        _fail(exc)


@template.command("list")
@pass_ctx
def template_list(ctx: Context):
    """List all service templates."""
    try:
        _print(ctx, ctx.client.get("/templates"))
    except ApiError as exc:
        _fail(exc)


@template.command("show")
@click.argument("template_id")
@pass_ctx
def template_show(ctx: Context, template_id):
    """Show a single service template."""
    try:
        _print(ctx, ctx.client.get(f"/templates/{template_id}"))
    except ApiError as exc:
        _fail(exc)


@template.command("delete")
@click.argument("template_id")
@pass_ctx
def template_delete(ctx: Context, template_id):
    """Delete a service template."""
    try:
        ctx.client.delete(f"/templates/{template_id}")
        click.echo(f"Template '{template_id}' deleted")
    except ApiError as exc:
        _fail(exc)


# ------------------------------------------------------------------ #
# ne (network element) group
# ------------------------------------------------------------------ #
@cli.group()
def ne():
    """Manage network elements known to this EDA instance."""


@ne.command("register")
@click.option("--name", default=None, help="Required unless --file is given")
@click.option("--type", "ne_type", default="generic", show_default=True)
@click.option("--ip", "management_ip", default=None, help="Required unless --file is given")
@click.option("--metadata", default=None, help="Inline JSON metadata")
@click.option("--metadata-file", type=click.Path(exists=True), default=None)
@click.option("--file", "file_path", type=click.Path(exists=True), help="Load full network-element JSON from file")
@pass_ctx
def ne_register(ctx: Context, name, ne_type, management_ip, metadata, metadata_file, file_path):
    """Register a network element that activations can target."""
    if not file_path and not (name and management_ip):
        raise click.UsageError("Either --file, or both --name and --ip, must be provided")
    try:
        if file_path:
            with open(file_path, "r", encoding="utf-8") as fh:
                body = json.load(fh)
        else:
            body = {
                "name": name,
                "ne_type": ne_type,
                "management_ip": management_ip,
                "metadata": _load_json_arg(metadata, metadata_file),
            }
        _print(ctx, ctx.client.post("/network-elements", body))
    except ApiError as exc:
        _fail(exc)


@ne.command("list")
@pass_ctx
def ne_list(ctx: Context):
    """List registered network elements."""
    try:
        _print(ctx, ctx.client.get("/network-elements"))
    except ApiError as exc:
        _fail(exc)


@ne.command("show")
@click.argument("ne_id")
@pass_ctx
def ne_show(ctx: Context, ne_id):
    """Show a single network element."""
    try:
        _print(ctx, ctx.client.get(f"/network-elements/{ne_id}"))
    except ApiError as exc:
        _fail(exc)


@ne.command("delete")
@click.argument("ne_id")
@pass_ctx
def ne_delete(ctx: Context, ne_id):
    """Delete/unregister a network element."""
    try:
        ctx.client.delete(f"/network-elements/{ne_id}")
        click.echo(f"Network element '{ne_id}' deleted")
    except ApiError as exc:
        _fail(exc)


@ne.command("block")
@click.argument("ne_id")
@pass_ctx
def ne_block(ctx: Context, ne_id):
    """Put an NE into maintenance mode: new activations targeting it are
    held instead of running (CUDB Activation Blocker equivalent)."""
    try:
        _print(ctx, ctx.client.post(f"/network-elements/{ne_id}/block"))
    except ApiError as exc:
        _fail(exc)


@ne.command("unblock")
@click.argument("ne_id")
@pass_ctx
def ne_unblock(ctx: Context, ne_id):
    """Take an NE out of maintenance mode and resume any held activations."""
    try:
        _print(ctx, ctx.client.post(f"/network-elements/{ne_id}/unblock"))
    except ApiError as exc:
        _fail(exc)


# ------------------------------------------------------------------ #
# activation group
# ------------------------------------------------------------------ #
@cli.group()
def activation():
    """Create and manage service activations (dynamic activation jobs)."""


def _merge_convenience_params(params: dict, webhook: Optional[str], auto_retry_max: Optional[int], auto_retry_backoff: Optional[float]) -> dict:
    if webhook:
        params["webhook_url"] = webhook
    if auto_retry_max is not None:
        params["auto_retry"] = {
            "max_attempts": auto_retry_max,
            "backoff_seconds": auto_retry_backoff if auto_retry_backoff is not None else 1.0,
        }
    return params


@activation.command("create")
@click.option("--template", "template_id", required=True)
@click.option("--ne", "ne_id", default=None, help="Target network element id (optional)")
@click.option("--params", default=None, help="Inline JSON activation parameters")
@click.option("--params-file", type=click.Path(exists=True), default=None)
@click.option("--webhook", default=None, help="URL to POST the final activation state to")
@click.option("--auto-retry-max", type=int, default=None, help="Auto-retry the workflow up to N attempts on failure")
@click.option("--auto-retry-backoff", type=float, default=None, help="Seconds to wait between auto-retry attempts (default 1.0)")
@click.option("--wait", is_flag=True, help="Block and stream logs until the activation finishes")
@pass_ctx
def activation_create(ctx: Context, template_id, ne_id, params, params_file, webhook, auto_retry_max, auto_retry_backoff, wait):
    """Start a new service activation from a template."""
    try:
        body_params = _load_json_arg(params, params_file)
        body_params = _merge_convenience_params(body_params, webhook, auto_retry_max, auto_retry_backoff)
        body = {
            "template_id": template_id,
            "ne_id": ne_id,
            "params": body_params,
        }
        result = ctx.client.post("/activations", body)
        _print(ctx, result)
        if wait and result.get("state") != "HELD":
            _stream_logs(ctx, result["id"])
    except ApiError as exc:
        _fail(exc)


@activation.command("batch")
@click.option("--file", "file_path", type=click.Path(exists=True), required=True,
              help="JSON file with {\"activations\": [{...}, {...}]} (Inbound Batch Handler equivalent)")
@pass_ctx
def activation_batch(ctx: Context, file_path):
    """Create many activations in a single call."""
    try:
        with open(file_path, "r", encoding="utf-8") as fh:
            body = json.load(fh)
        _print(ctx, ctx.client.post("/activations/batch", body))
    except ApiError as exc:
        _fail(exc)


@activation.command("list")
@pass_ctx
def activation_list(ctx: Context):
    """List all activations."""
    try:
        _print(ctx, ctx.client.get("/activations"))
    except ApiError as exc:
        _fail(exc)


@activation.command("show")
@click.argument("activation_id")
@pass_ctx
def activation_show(ctx: Context, activation_id):
    """Show a single activation."""
    try:
        _print(ctx, ctx.client.get(f"/activations/{activation_id}"))
    except ApiError as exc:
        _fail(exc)


@activation.command("status")
@click.argument("activation_id")
@pass_ctx
def activation_status(ctx: Context, activation_id):
    """Show the current state of an activation."""
    try:
        _print(ctx, ctx.client.get(f"/activations/{activation_id}/status"))
    except ApiError as exc:
        _fail(exc)


def _stream_logs(ctx: Context, activation_id: str) -> None:
    seen = 0
    while True:
        data = ctx.client.get(f"/activations/{activation_id}/logs")
        logs = data["logs"]
        for entry in logs[seen:]:
            ts = time.strftime("%H:%M:%S", time.localtime(entry["ts"]))
            click.echo(f"[{ts}] {entry['message']}")
        seen = len(logs)
        act = ctx.client.get(f"/activations/{activation_id}")
        if act["state"] in TERMINAL_STATES:
            click.echo(f"-- final state: {act['state']} --")
            break
        time.sleep(0.5)


@activation.command("logs")
@click.argument("activation_id")
@click.option("--follow", "-f", is_flag=True, help="Stream logs until the activation reaches a final state")
@pass_ctx
def activation_logs(ctx: Context, activation_id, follow):
    """Show (or follow) the activation log."""
    try:
        if follow:
            _stream_logs(ctx, activation_id)
        else:
            data = ctx.client.get(f"/activations/{activation_id}/logs")
            if ctx.as_json:
                _print(ctx, data)
            else:
                for entry in data["logs"]:
                    ts = time.strftime("%H:%M:%S", time.localtime(entry["ts"]))
                    click.echo(f"[{ts}] {entry['message']}")
    except ApiError as exc:
        _fail(exc)


@activation.command("deactivate")
@click.argument("activation_id")
@click.option("--wait", is_flag=True, help="Block and stream logs until deactivation finishes")
@pass_ctx
def activation_deactivate(ctx: Context, activation_id, wait):
    """Deactivate (tear down) an active or failed activation."""
    try:
        result = ctx.client.post(f"/activations/{activation_id}/deactivate")
        _print(ctx, result)
        if wait:
            _stream_logs(ctx, activation_id)
    except ApiError as exc:
        _fail(exc)


@activation.command("retry")
@click.argument("activation_id")
@click.option("--wait", is_flag=True, help="Block and stream logs until retry finishes")
@pass_ctx
def activation_retry(ctx: Context, activation_id, wait):
    """Retry a failed activation from the beginning."""
    try:
        result = ctx.client.post(f"/activations/{activation_id}/retry")
        _print(ctx, result)
        if wait:
            _stream_logs(ctx, activation_id)
    except ApiError as exc:
        _fail(exc)


@activation.command("delete")
@click.argument("activation_id")
@pass_ctx
def activation_delete(ctx: Context, activation_id):
    """Delete an activation record."""
    try:
        ctx.client.delete(f"/activations/{activation_id}")
        click.echo(f"Activation '{activation_id}' deleted")
    except ApiError as exc:
        _fail(exc)


# ------------------------------------------------------------------ #
# alarm group
# ------------------------------------------------------------------ #
@cli.group()
def alarm():
    """View and clear fault-management alarms."""


@alarm.command("list")
@click.option("--active", is_flag=True, help="Only show uncleared alarms")
@pass_ctx
def alarm_list(ctx: Context, active):
    """List alarms raised by the engine."""
    try:
        _print(ctx, ctx.client.get("/alarms", params={"active": active}))
    except ApiError as exc:
        _fail(exc)


@alarm.command("clear")
@click.argument("alarm_id")
@pass_ctx
def alarm_clear(ctx: Context, alarm_id):
    """Clear an alarm."""
    try:
        _print(ctx, ctx.client.post(f"/alarms/{alarm_id}/clear"))
    except ApiError as exc:
        _fail(exc)


if __name__ == "__main__":
    cli()
