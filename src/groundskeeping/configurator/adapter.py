"""Read-only adapter over the public shape of `oa-configurator` stack models."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from enum import Enum
from pathlib import Path

from oa_configurator import (
    CDMDatabaseConfig,
    ConnectionConfig,
    GenericDatabaseConfig,
    LoggingConfig,
    ModelConfig,
    PackageConfigBase,
    ProviderConfig,
    RefTo,
    Sensitive,
    StackConfig,
    VectorStoreConfig,
    mismatched_kind_refs,
    unresolved_refs,
)
from pydantic import BaseModel

from groundskeeping.configurator.models import (
    ConfigDiff,
    ConfigDiffEntry,
    ConfigDraft,
    ConfigReferenceStatus,
    ConfigReferenceView,
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

_SECRET_FIELD_NAMES = frozenset(
    {"api_key", "credential", "key", "passwd", "password", "secret", "token"}
)
_REFERENCE_TARGET_KINDS: dict[type[BaseModel], ConfigTargetKind] = {
    ConnectionConfig: ConfigTargetKind.CONNECTION,
    GenericDatabaseConfig: ConfigTargetKind.DATABASE,
    CDMDatabaseConfig: ConfigTargetKind.DATABASE,
    ProviderConfig: ConfigTargetKind.PROVIDER,
    ModelConfig: ConfigTargetKind.MODEL,
    VectorStoreConfig: ConfigTargetKind.VECTOR_STORE,
}


class OAConfiguratorAdapter:
    """Build safe, read-only views from an oa-configurator 1.x stack.

    Core sections are read from the public ``StackConfig`` and concrete pydantic models.
    A caller may additionally provide resolved ``PackageConfigBase`` instances so tool
    fields can receive the same typed sensitivity and reference inspection. Editable
    candidates and persistence remain outside groundskeeping.
    """

    def snapshot(
        self,
        stack_config: StackConfig,
        *,
        config_path: str | Path | None = None,
        package_configs: Iterable[PackageConfigBase] = (),
        title: str = "Stack configuration",
    ) -> ConfiguratorSnapshot:
        sections = (
            self._mapping_section(
                ConfigTargetKind.CONNECTION,
                "Connections",
                stack_config.connections,
                stack_config,
            ),
            self._mapping_section(
                ConfigTargetKind.DATABASE,
                "Databases",
                stack_config.databases,
                stack_config,
            ),
            self._mapping_section(
                ConfigTargetKind.PROVIDER,
                "Providers",
                stack_config.providers,
                stack_config,
            ),
            self._mapping_section(
                ConfigTargetKind.MODEL,
                "Models",
                stack_config.models,
                stack_config,
            ),
            self._mapping_section(
                ConfigTargetKind.VECTOR_STORE,
                "Vector stores",
                stack_config.vector_stores,
                stack_config,
            ),
            self._tool_section(stack_config, tuple(package_configs)),
            self._logging_section(stack_config.logging, stack_config),
        )
        return ConfiguratorSnapshot(
            title=title,
            path=str(config_path)
            if config_path is not None
            else str(stack_config.loaded_path)
            if stack_config.loaded_path is not None
            else None,
            sections=sections,
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
        values: Mapping[str, BaseModel],
        stack_config: StackConfig,
    ) -> ConfigSectionView:
        children = tuple(
            self._typed_entry(kind, key, value, stack_config)
            for key, value in sorted(values.items())
        )
        return ConfigSectionView(
            target=ConfigTarget(
                kind=kind,
                key=kind.value,
                title=title,
                status=self._group_status(children),
            ),
            fields={"count": len(children)},
            children=children,
        )

    def _tool_section(
        self,
        stack_config: StackConfig,
        package_configs: tuple[PackageConfigBase, ...],
    ) -> ConfigSectionView:
        known = {type(package).tool_name: package for package in package_configs}
        children = []
        for key in sorted(set(stack_config.tools) | set(known)):
            package = known.get(key)
            if package is not None:
                children.append(
                    self._typed_entry(
                        ConfigTargetKind.TOOL,
                        key,
                        package,
                        stack_config,
                    )
                )
                continue
            children.append(
                ConfigSectionView(
                    target=ConfigTarget(
                        kind=ConfigTargetKind.TOOL,
                        key=key,
                        title=key,
                        status=SemanticStatus.WARNING,
                    ),
                    fields=self._safe_untyped_fields(stack_config.tools[key]),
                    notes=(
                        "Package schema unavailable; reference status is unknown.",
                    ),
                )
            )
        child_tuple = tuple(children)
        return ConfigSectionView(
            target=ConfigTarget(
                kind=ConfigTargetKind.TOOL,
                key=ConfigTargetKind.TOOL.value,
                title="Tools",
                status=self._group_status(child_tuple),
            ),
            fields={"count": len(child_tuple)},
            children=child_tuple,
        )

    def _logging_section(
        self,
        logging_config: LoggingConfig,
        stack_config: StackConfig,
    ) -> ConfigSectionView:
        fields, notes, status = self._typed_fields(logging_config, stack_config)
        is_default = logging_config == LoggingConfig()
        return ConfigSectionView(
            target=ConfigTarget(
                kind=ConfigTargetKind.LOGGING,
                key=ConfigTargetKind.LOGGING.value,
                title="Logging",
                status=SemanticStatus.IDLE if is_default else status,
            ),
            fields=fields,
            notes=("Using default logging settings.",) if is_default else notes,
        )

    def _typed_entry(
        self,
        kind: ConfigTargetKind,
        key: str,
        value: BaseModel,
        stack_config: StackConfig,
    ) -> ConfigSectionView:
        fields, notes, status = self._typed_fields(value, stack_config)
        return ConfigSectionView(
            target=ConfigTarget(
                kind=kind,
                key=key,
                title=key,
                status=status,
            ),
            fields=fields,
            notes=notes,
        )

    def _typed_fields(
        self,
        value: BaseModel,
        stack_config: StackConfig,
    ) -> tuple[Mapping[str, object], tuple[str, ...], SemanticStatus]:
        unresolved = {
            field_name: (name, section)
            for field_name, name, section in unresolved_refs(value, stack_config)
        }
        mismatched = {
            field_name: (name, expected, actual)
            for field_name, name, expected, actual in mismatched_kind_refs(
                value, stack_config
            )
        }
        fields: dict[str, object] = {}
        notes: list[str] = []
        for name, info in type(value).model_fields.items():
            item = getattr(value, name)
            if self._is_sensitive_field(name, info.metadata):
                fields[name] = RedactedValue()
                continue
            ref = next((marker for marker in info.metadata if isinstance(marker, RefTo)), None)
            if ref is not None and item is not None:
                reference = self._reference_view(
                    name,
                    str(item),
                    ref,
                    unresolved,
                    mismatched,
                )
                fields[name] = reference
                if reference.status is ConfigReferenceStatus.MISSING:
                    notes.append(f"{name} points to missing {reference.section.value} {reference.name!r}.")
                elif reference.status is ConfigReferenceStatus.WRONG_KIND:
                    notes.append(
                        f"{name} points to {reference.name!r}, which is {reference.actual_type}; expected {reference.expected_type}."
                    )
                continue
            fields[name] = self._display_value(item)
        status = SemanticStatus.ERROR if notes else SemanticStatus.OK
        return fields, tuple(notes), status

    def _reference_view(
        self,
        field_name: str,
        name: str,
        ref: RefTo,
        unresolved: Mapping[str, tuple[str, str]],
        mismatched: Mapping[str, tuple[str, type[BaseModel], type[BaseModel]]],
    ) -> ConfigReferenceView:
        expected_type = ref.target.__name__
        section = _REFERENCE_TARGET_KINDS[ref.target]
        mismatch = mismatched.get(field_name)
        if mismatch is not None:
            return ConfigReferenceView(
                section=section,
                name=name,
                status=ConfigReferenceStatus.WRONG_KIND,
                expected_type=expected_type,
                actual_type=mismatch[2].__name__,
            )
        if field_name in unresolved:
            return ConfigReferenceView(
                section=section,
                name=name,
                status=ConfigReferenceStatus.MISSING,
                expected_type=expected_type,
            )
        return ConfigReferenceView(
            section=section,
            name=name,
            status=ConfigReferenceStatus.RESOLVED,
            expected_type=expected_type,
        )

    def _safe_untyped_fields(self, value: Mapping[str, object]) -> Mapping[str, object]:
        return {
            str(name): self._display_value(
                item,
                sensitive=self._is_sensitive_name(str(name)),
            )
            for name, item in value.items()
        }

    def _display_value(self, value: object, *, sensitive: bool = False) -> object:
        safe = self._redact_nested(value, sensitive=sensitive)
        if self._looks_scalar(safe):
            return safe
        return self._summarize(safe)

    def _redact_nested(self, value: object, *, sensitive: bool = False) -> object:
        if sensitive:
            return RedactedValue()
        if isinstance(value, BaseModel):
            return {
                name: self._redact_nested(
                    getattr(value, name),
                    sensitive=self._is_sensitive_field(name, info.metadata),
                )
                for name, info in type(value).model_fields.items()
            }
        if isinstance(value, Mapping):
            return {
                str(name): self._redact_nested(
                    item,
                    sensitive=self._is_sensitive_name(str(name)),
                )
                for name, item in value.items()
            }
        if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
            return tuple(self._redact_nested(item) for item in value)
        if isinstance(value, set | frozenset):
            return tuple(self._redact_nested(item) for item in value)
        if isinstance(value, Enum):
            return value.value
        if isinstance(value, Path):
            return str(value)
        return value

    def _is_sensitive_field(self, name: str, metadata: Sequence[object]) -> bool:
        return any(isinstance(marker, Sensitive) for marker in metadata) or self._is_sensitive_name(name)

    def _is_sensitive_name(self, name: str) -> bool:
        normalized = name.lower().replace("-", "_")
        return normalized in _SECRET_FIELD_NAMES or normalized.endswith(
            ("_password", "_secret", "_token", "_api_key")
        )

    def _group_status(self, children: tuple[ConfigSectionView, ...]) -> SemanticStatus:
        statuses = {child.target.status for child in children}
        if SemanticStatus.ERROR in statuses:
            return SemanticStatus.ERROR
        if SemanticStatus.WARNING in statuses:
            return SemanticStatus.WARNING
        if not children:
            return SemanticStatus.IDLE
        return SemanticStatus.OK

    def _section_to_node(self, section: ConfigSectionView) -> TreeNode:
        fields = dict(section.fields)
        for index, note in enumerate(section.notes, start=1):
            fields["note" if len(section.notes) == 1 else f"note {index}"] = note
        return TreeNode(
            label=section.target.title,
            status=section.target.status,
            fields=fields,
            children=tuple(self._section_to_node(child) for child in section.children),
        )

    def _looks_scalar(self, value: object) -> bool:
        return value is None or isinstance(value, str | int | float | bool | RedactedValue)

    def _summarize(self, value: object) -> str:
        if isinstance(value, Mapping):
            return f"{len(value)} entries"
        if isinstance(value, Sequence | set | frozenset) and not isinstance(
            value, str | bytes | bytearray
        ):
            return f"{len(value)} items"
        return type(value).__name__


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
