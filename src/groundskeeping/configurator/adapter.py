"""Read-only adapter over the public shape of `oa-configurator` stack models."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import is_dataclass
from pathlib import Path

from groundskeeping.configurator.models import (
    ConfigDiff,
    ConfigDiffEntry,
    ConfigDraft,
    ConfigResourceAdapter,
    ConfigSectionView,
    ConfigTarget,
    ConfigTargetKind,
    ConfiguratorSnapshot,
    RedactedValue,
)
from groundskeeping.contracts.actions import FieldSpec, ValidationIssue
from groundskeeping.contracts.views import SemanticStatus, TreeNode, TreeView
from groundskeeping.contracts.wizards import WizardController

_SECRET_FIELD_NAMES = frozenset({"password", "secret", "token", "api_key"})


class OAConfiguratorAdapter:
    """Build safe, read-only views from public `oa-configurator` model objects.

    The adapter is deliberately structural: tests and demos can pass fakes, while real
    consumers pass `StackConfig` and `PackageConfigBase` instances from `oa-configurator`.
    Editable drafts and persistence are intentionally left for a later phase that can use
    a public revision-aware mutation API.
    """

    def snapshot(
        self,
        stack_config: object,
        *,
        config_path: str | Path | None = None,
        package_configs: Iterable[object] = (),
        title: str = "Stack configuration",
    ) -> ConfiguratorSnapshot:
        package_configs = tuple(package_configs)
        sections = (
            self._mapping_section(
                ConfigTargetKind.CONNECTION,
                "Connections",
                getattr(stack_config, "connections", None),
            ),
            self._mapping_section(
                ConfigTargetKind.DATABASE,
                "Databases",
                getattr(stack_config, "databases", None),
            ),
            self._mapping_section(
                ConfigTargetKind.PROVIDER,
                "Providers",
                getattr(stack_config, "providers", None),
            ),
            self._mapping_section(
                ConfigTargetKind.MODEL,
                "Models",
                getattr(stack_config, "models", None),
            ),
            self._mapping_section(
                ConfigTargetKind.VECTOR_STORE,
                "Vector stores",
                getattr(stack_config, "vector_stores", None),
            ),
            self._tool_section(getattr(stack_config, "tools", None), package_configs),
            self._singleton_section(
                ConfigTargetKind.LOGGING,
                "Logging",
                getattr(stack_config, "logging", None),
            ),
        )
        return ConfiguratorSnapshot(
            title=title,
            path=str(config_path)
            if config_path is not None
            else self._string_attr(stack_config, "loaded_path"),
            sections=tuple(section for section in sections if section is not None),
        )

    def as_tree_view(self, snapshot: ConfiguratorSnapshot) -> TreeView:
        rows = tuple(self._section_to_node(section) for section in snapshot.sections)
        details = []
        if snapshot.path:
            details.append(f"path: {snapshot.path}")
        return TreeView(
            title=snapshot.title,
            message="; ".join(details) if details else "read-only inspection",
            status=SemanticStatus.INFO,
            rows=rows,
        )

    def diff(
        self,
        target: ConfigTarget,
        original_fields: Mapping[str, object],
        candidate_fields: Mapping[str, object],
        *,
        sensitive_fields: frozenset[str] = frozenset(),
    ) -> ConfigDiff:
        """Build a redacted structural diff for confirmation surfaces."""
        fields = sorted(set(original_fields) | set(candidate_fields))
        entries: list[ConfigDiffEntry] = []
        for field in fields:
            before = original_fields.get(field)
            after = candidate_fields.get(field)
            if before == after:
                continue
            sensitive = field in sensitive_fields or isinstance(before, RedactedValue) or isinstance(after, RedactedValue)
            entries.append(
                ConfigDiffEntry(
                    field=field,
                    before=RedactedValue() if sensitive else before,
                    after=RedactedValue() if sensitive else after,
                    sensitive=sensitive,
                )
            )
        return ConfigDiff(target=target, entries=tuple(entries))

    def wizard_controller(
        self,
        target: ConfigTarget,
        adapters: Iterable[ConfigResourceAdapter],
    ) -> WizardController | None:
        """Return the first consumer adapter that can drive a setup wizard.

        Groundskeeping only brokers the Textual-free controller. The adapter that
        understands the resource still owns candidate state, validation, revision checks,
        and apply semantics.
        """

        for adapter in adapters:
            if adapter.supports(target):
                return adapter.wizard_controller(target)
        return None

    def _mapping_section(
        self,
        kind: ConfigTargetKind,
        title: str,
        values: object,
    ) -> ConfigSectionView | None:
        mapping = self._as_mapping(values)
        if not mapping:
            return None
        children = tuple(
            ConfigSectionView(
                target=ConfigTarget(kind=kind, key=str(key), title=str(key)),
                fields=self._safe_fields(value),
            )
            for key, value in sorted(mapping.items(), key=lambda item: str(item[0]))
        )
        return ConfigSectionView(
            target=ConfigTarget(kind=kind, key=kind.value, title=title),
            fields={"count": len(children)},
            children=children,
        )

    def _tool_section(
        self,
        values: object,
        package_configs: tuple[object, ...],
    ) -> ConfigSectionView | None:
        tools = dict(self._as_mapping(values))
        for package_config in package_configs:
            key = self._string_attr(
                package_config,
                "tool_name",
                "package_key",
                "package_name",
                "name",
            )
            tools[key or type(package_config).__name__] = package_config
        return self._mapping_section(ConfigTargetKind.TOOL, "Tools", tools)

    def _singleton_section(
        self,
        kind: ConfigTargetKind,
        title: str,
        value: object,
    ) -> ConfigSectionView | None:
        if value is None:
            return None
        return ConfigSectionView(
            target=ConfigTarget(kind=kind, key=kind.value, title=title),
            fields=self._safe_fields(value),
        )

    def _section_to_node(self, section: ConfigSectionView) -> TreeNode:
        return TreeNode(
            label=section.target.title,
            status=section.target.status,
            fields=section.fields,
            children=tuple(self._section_to_node(child) for child in section.children),
        )

    def _safe_fields(self, value: object) -> Mapping[str, object]:
        raw = self._object_mapping(value)
        safe: dict[str, object] = {}
        for key, item in raw.items():
            name = str(key)
            if name.lower() in _SECRET_FIELD_NAMES:
                safe[name] = RedactedValue()
            elif self._looks_scalar(item):
                safe[name] = item
            else:
                safe[name] = self._summarize(item)
        return safe

    def _object_mapping(self, value: object) -> Mapping[str, object]:
        mapping = self._as_mapping(value)
        if mapping:
            return {str(key): item for key, item in mapping.items()}
        model_dump = getattr(value, "model_dump", None)
        if callable(model_dump):
            dumped = model_dump()
            if isinstance(dumped, Mapping):
                return {str(key): item for key, item in dumped.items()}
        if is_dataclass(value):
            return {
                key: getattr(value, key)
                for key in getattr(value, "__dataclass_fields__", {})
            }
        if hasattr(value, "__dict__"):
            return {
                key: item
                for key, item in vars(value).items()
                if not key.startswith("_")
            }
        return {"value": value}

    def _as_mapping(self, value: object) -> Mapping[object, object]:
        if isinstance(value, Mapping):
            items: dict[object, object] = {key: item for key, item in value.items()}
            return items
        return {}

    def _looks_scalar(self, value: object) -> bool:
        return value is None or isinstance(value, str | int | float | bool | RedactedValue)

    def _summarize(self, value: object) -> str:
        mapping = self._as_mapping(value)
        if mapping:
            return f"{len(mapping)} entries"
        if isinstance(value, (list, tuple, set, frozenset)):
            return f"{len(value)} items"
        return type(value).__name__

    def _string_attr(self, value: object, *names: str) -> str | None:
        for name in names:
            item = getattr(value, name, None)
            if item is not None:
                return str(item)
        return None


class NativeConfigResourceAdapter:
    """Fallback adapter for ordinary configuration sections.

    Consumers can register exact adapters for richer resource semantics. This fallback is
    intentionally plain: it offers display fields and validates nothing beyond the model
    layer that `oa-configurator` will run during a real apply.
    """

    key = "native"

    def supports(self, target: ConfigTarget) -> bool:
        return True

    def describe(self, target: ConfigTarget) -> ConfigSectionView:
        return ConfigSectionView(target=target)

    def fields(self, target: ConfigTarget) -> tuple[FieldSpec, ...]:
        return ()

    def validate(self, draft: ConfigDraft) -> tuple[ValidationIssue, ...]:
        return ()

    def post_apply_effects(self, draft: ConfigDraft) -> tuple[str, ...]:
        return ()

    def wizard_controller(self, target: ConfigTarget) -> WizardController | None:
        return None
