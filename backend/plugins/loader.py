from __future__ import annotations

from dataclasses import dataclass, field
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, ValidationError

from plugins.schema import PluginSchema


PLUGIN_DIR = Path(__file__).resolve().parent
REGISTRY_PATH = PLUGIN_DIR / "registry.json"
TOOLS_DIR = PLUGIN_DIR / "tools"
MASTER_SCHEMA_PATH = PLUGIN_DIR / "master_schema.json"


@dataclass
class PluginRecord:
    name: str
    plugin_dir: Path
    schema_path: Path
    schema: PluginSchema | None = None
    permissions: dict[str, Any] = field(default_factory=dict)
    examples: list[dict[str, Any]] = field(default_factory=list)
    status: str = "invalid"
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        data = self.schema.model_dump() if self.schema else {"tool_name": self.name, "name": self.name}
        data.update(
            {
                "status": self.status,
                "errors": list(self.errors),
                "declared_permissions": dict(self.permissions),
                "examples": list(self.examples),
                "examples_count": len(self.examples),
            }
        )
        return data


class PluginLoader:
    def __init__(
        self,
        registry_path: Path = REGISTRY_PATH,
        tools_dir: Path = TOOLS_DIR,
        master_schema_path: Path = MASTER_SCHEMA_PATH,
    ) -> None:
        self.registry_path = registry_path
        self.tools_dir = tools_dir
        self.master_schema_path = master_schema_path
        self._records: dict[str, PluginRecord] | None = None

    def list_plugins(self) -> list[dict[str, Any]]:
        return [record.as_dict() for record in self.discover_records().values()]

    def ready_plugins(self) -> dict[str, PluginRecord]:
        return {name: record for name, record in self.discover_records().items() if record.status == "ready"}

    def invalid_plugins(self) -> dict[str, PluginRecord]:
        return {name: record for name, record in self.discover_records().items() if record.status == "invalid"}

    def get_plugin(self, name: str) -> PluginSchema | None:
        record = self.ready_plugins().get(name)
        return record.schema if record else None

    def get_record(self, name: str) -> PluginRecord | None:
        return self.discover_records().get(name)

    def run_plugin(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        record = self.ready_plugins().get(name)
        plugin = record.schema if record else None
        if plugin is None or not plugin.enabled:
            raise PluginNotFoundError(name)

        plugin_dir = record.plugin_dir
        entry_path = (plugin_dir / plugin.entry_file).resolve()
        if plugin_dir.resolve() not in entry_path.parents:
            raise PluginValidationError("Plugin entry file must stay inside its plugin directory.")
        if not entry_path.exists():
            raise PluginValidationError(f"Plugin entry file not found: {plugin.entry_file}")

        module = _load_module(f"jarvis_plugin_{plugin.tool_name}", entry_path)
        _validate_module_contract(module, plugin)
        result = getattr(module, plugin.entry_function)(args)
        if not isinstance(result, dict):
            raise PluginValidationError("Plugin run function must return a dict.")
        return result

    def discover_plugins(self) -> dict[str, PluginSchema]:
        return {
            name: record.schema
            for name, record in self.ready_plugins().items()
            if record.schema is not None
        }

    def discover_records(self) -> dict[str, PluginRecord]:
        if self._records is not None:
            return self._records

        registry = self._load_registry()
        records: dict[str, PluginRecord] = {}
        if not self.tools_dir.exists():
            self._records = records
            return records

        validator = self._master_validator()

        for schema_path in sorted(self.tools_dir.glob("*/tool.schema.json")):
            plugin_dir = schema_path.parent
            record = PluginRecord(name=plugin_dir.name, plugin_dir=plugin_dir, schema_path=schema_path)
            try:
                data = json.loads(schema_path.read_text(encoding="utf-8"))
                _validate_json_schema(validator, data)
                plugin = PluginSchema(**data)
                record.name = plugin.tool_name
                if registry and plugin.tool_name not in registry:
                    continue
                if plugin.tool_name in registry:
                    plugin.enabled = registry[plugin.tool_name].get("enabled", plugin.enabled)
                record.schema = plugin
                record.permissions = _load_required_json_object(plugin_dir / "permissions.json")
                record.examples = _load_required_examples(plugin_dir / "examples.json")
                _validate_contract_files(plugin_dir, plugin)
                record.status = "ready" if plugin.enabled else "disabled"
            except Exception as exc:
                record.errors.append(str(exc))
            records[record.name] = record

        self._records = records
        return records

    def _load_registry(self) -> dict[str, dict[str, Any]]:
        if not self.registry_path.exists():
            return {}
        data = json.loads(self.registry_path.read_text(encoding="utf-8"))
        return {item["tool_name"]: item for item in data.get("plugins", [])}

    def _master_validator(self) -> Draft202012Validator:
        if not self.master_schema_path.exists():
            raise PluginValidationError(f"Master plugin schema not found: {self.master_schema_path}")
        schema = json.loads(self.master_schema_path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        return Draft202012Validator(schema)


class PluginNotFoundError(LookupError):
    pass


class PluginValidationError(RuntimeError):
    pass


def _load_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise PluginValidationError(f"Unable to load plugin module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _validate_module_contract(module, plugin: PluginSchema) -> None:
    plugin_name = getattr(module, "PLUGIN_NAME", plugin.tool_name)
    if plugin_name != plugin.tool_name:
        raise PluginValidationError("PLUGIN_NAME must match tool.schema.json.")
    plugin_version = getattr(module, "PLUGIN_VERSION", plugin.version)
    if plugin_version != plugin.version:
        raise PluginValidationError("PLUGIN_VERSION must match tool.schema.json.")
    plugin_permissions = getattr(module, "PLUGIN_PERMISSIONS", plugin.permissions)
    if plugin_permissions != plugin.permissions:
        raise PluginValidationError("PLUGIN_PERMISSIONS must match tool.schema.json.")
    run_function = getattr(module, plugin.entry_function, None)
    if not callable(run_function):
        raise PluginValidationError(f"Plugin entry function is not callable: {plugin.entry_function}")


def _validate_json_schema(validator: Draft202012Validator, data: dict[str, Any]) -> None:
    try:
        validator.validate(data)
    except ValidationError as exc:
        path = ".".join(str(part) for part in exc.absolute_path)
        location = f" at {path}" if path else ""
        raise PluginValidationError(f"tool.schema.json failed master schema validation{location}: {exc.message}") from exc


def _load_required_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise PluginValidationError(f"Missing required file: {path.name}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise PluginValidationError(f"{path.name} must contain a JSON object.")
    return data


def _load_required_examples(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise PluginValidationError(f"Missing required file: {path.name}")
    data = json.loads(path.read_text(encoding="utf-8"))
    examples = data.get("examples") if isinstance(data, dict) else data
    if not isinstance(examples, list):
        raise PluginValidationError("examples.json must contain an examples array.")
    return [item for item in examples if isinstance(item, dict)]


def _validate_contract_files(plugin_dir: Path, plugin: PluginSchema) -> None:
    tool_path = plugin_dir / plugin.entry_file
    if not tool_path.exists():
        raise PluginValidationError(f"Plugin entry file not found: {plugin.entry_file}")
    if not (plugin_dir / "tool.py").exists():
        raise PluginValidationError("Missing required file: tool.py")
    if plugin.entry_function != "run":
        raise PluginValidationError("Plugin entry function must be run.")
