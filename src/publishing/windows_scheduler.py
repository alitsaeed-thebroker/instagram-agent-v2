"""Least-privilege Windows Task Scheduler adapter for the publishing worker."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime,timedelta,timezone
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable
from xml.etree.ElementTree import Element, SubElement, tostring

from .worker import WorkerError, WorkerState, ledger_precheck, worker_config


@dataclass(frozen=True)
class TaskDefinition:
    task_name: str
    executable: str
    arguments: str
    working_directory: str
    poll_interval_minutes: int


class WindowsTaskSchedulerAdapter:
    def __init__(self, runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run) -> None:
        self.runner = runner

    def install(self, definition: TaskDefinition) -> dict[str, Any]:
        xml = task_xml(definition)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile("w", suffix=".xml", encoding="utf-16", delete=False) as handle:
                handle.write(xml); temporary = handle.name
            result = self.runner(["schtasks.exe", "/Create", "/TN", definition.task_name, "/XML", temporary, "/F"],
                                 capture_output=True, text=True, check=False)
            if result.returncode: raise WorkerError("Windows Task Scheduler installation failed: " + _bounded(result.stderr or result.stdout))
            return {"installed": True, "updated": True, "task_name": definition.task_name}
        finally:
            if temporary:
                try: os.unlink(temporary)
                except OSError: pass

    def uninstall(self, task_name: str) -> dict[str, Any]:
        result = self.runner(["schtasks.exe", "/Delete", "/TN", task_name, "/F"], capture_output=True, text=True, check=False)
        if result.returncode and "cannot find" not in (result.stderr + result.stdout).casefold():
            raise WorkerError("Windows Task Scheduler removal failed: " + _bounded(result.stderr or result.stdout))
        return {"installed": False, "task_name": task_name}

    def set_enabled(self, task_name: str, enabled: bool) -> None:
        result = self.runner(["schtasks.exe", "/Change", "/TN", task_name, "/ENABLE" if enabled else "/DISABLE"], capture_output=True, text=True, check=False)
        if result.returncode and "cannot find" not in (result.stderr + result.stdout).casefold():
            raise WorkerError("Windows Task Scheduler state change failed: " + _bounded(result.stderr or result.stdout))

    def status(self, task_name: str) -> dict[str, Any]:
        result = self.runner(["schtasks.exe", "/Query", "/TN", task_name, "/FO", "LIST", "/V"], capture_output=True, text=True, check=False)
        if result.returncode: return {"installed": False, "task_name": task_name}
        fields = {}
        for line in result.stdout.splitlines():
            if ":" in line:
                key, value = line.split(":", 1); fields[key.strip().casefold().replace(" ", "_")] = value.strip()
        return {"installed": True, "task_name": task_name, "enabled": "disabled" not in fields.get("scheduled_task_state", fields.get("status", "")).casefold(),
                "last_run_time": fields.get("last_run_time"), "last_result": fields.get("last_result"), "next_run_time": fields.get("next_run_time"),
                "configured_command": fields.get("task_to_run")}


def desired_task(root: Path, executable: Path | None = None) -> TaskDefinition:
    root = root.resolve(); python = (executable or Path(sys.executable)).resolve(); app = root / "app.py"
    if not root.is_dir() or not app.is_file(): raise WorkerError("Repository path is invalid")
    if not python.is_file(): raise WorkerError("Python interpreter path is invalid")
    config = worker_config(root)
    return TaskDefinition(config["task_name"], str(python), f'"{app}" --publishing-worker', str(root), config["poll_interval_minutes"])


def install_worker(root: Path, *, dry_run: bool = False, adapter: WindowsTaskSchedulerAdapter | None = None,
                   executable: Path | None = None) -> dict[str, Any]:
    definition = desired_task(root, executable)
    ledger_health = "valid"
    try: ledger_health = ledger_precheck(root, initialize_fresh=not dry_run)
    except Exception as error:
        ledger_health = str(error)
        if not dry_run: raise
    report = {**asdict(definition), "dry_run": dry_run, "secrets_present": False, "ledger_health": ledger_health,
              "installation_ready": ledger_health in {"valid", "valid_fresh_install", "initialized_fresh"}}
    if dry_run: return {**report, "installed": False, "mutated": False}
    if os.name != "nt": raise WorkerError("Windows Task Scheduler installation is available only on Windows")
    return {**report, **(adapter or WindowsTaskSchedulerAdapter()).install(definition), "mutated": True}


def task_xml(definition: TaskDefinition) -> str:
    task = Element("Task", {"version": "1.4", "xmlns": "http://schemas.microsoft.com/windows/2004/02/mit/task"})
    settings = SubElement(task, "Settings"); SubElement(settings, "MultipleInstancesPolicy").text = "IgnoreNew"
    SubElement(settings, "StartWhenAvailable").text = "true"; SubElement(settings, "ExecutionTimeLimit").text = "PT10M"
    triggers = SubElement(task, "Triggers"); trigger = SubElement(triggers, "TimeTrigger"); SubElement(trigger, "Enabled").text = "true"
    SubElement(trigger, "StartBoundary").text = (datetime.now(timezone.utc).replace(second=0,microsecond=0)+timedelta(minutes=1)).isoformat()
    repetition = SubElement(trigger, "Repetition"); SubElement(repetition, "Interval").text = f"PT{definition.poll_interval_minutes}M"; SubElement(repetition, "StopAtDurationEnd").text = "false"
    principals = SubElement(task, "Principals"); principal = SubElement(principals, "Principal", {"id": "Author"}); SubElement(principal, "LogonType").text = "InteractiveToken"; SubElement(principal, "RunLevel").text = "LeastPrivilege"
    actions = SubElement(task, "Actions", {"Context": "Author"}); execute = SubElement(actions, "Exec")
    SubElement(execute, "Command").text = definition.executable; SubElement(execute, "Arguments").text = definition.arguments; SubElement(execute, "WorkingDirectory").text = definition.working_directory
    return '<?xml version="1.0" encoding="UTF-16"?>\n' + tostring(task, encoding="unicode")


def scheduler_status(root: Path, adapter: WindowsTaskSchedulerAdapter | None = None) -> dict[str, Any]:
    definition = desired_task(root); state = WorkerState(root); config = worker_config(root)
    remote = (adapter or WindowsTaskSchedulerAdapter()).status(definition.task_name) if os.name == "nt" or adapter else {"installed": False, "task_name": definition.task_name}
    health = "healthy" if not remote.get("installed") or remote.get("configured_command") in {None, definition.executable + " " + definition.arguments} else "configuration_mismatch"
    return {**remote, "desired": asdict(definition), "worker_enabled": state.enabled(config["enabled_by_default"]), "configuration_health": health}


def _bounded(value: str) -> str:
    return " ".join(value.split())[:500]
