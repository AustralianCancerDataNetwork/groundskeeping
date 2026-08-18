"""Read-only adapter over the public shape of `oa-configurator` stack models."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from enum import Enum
from importlib.metadata import entry_points
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
    StackConfig,
    VectorStoreConfig,
    is_sensitive,
    mismatched_kind_refs,
    safe_endpoint,
    unresolved_refs,
)
from pydantic import BaseModel

from groundskeeping.configurator.models import (
    ConfigReferenceStatus,
    ConfigReferenceView,
    ConfigSectionView,
    ConfigTarget,
    ConfigTargetKind,
    ConfiguratorSnapshot,
    RedactedValue,
)
from groundskeeping.contracts.views import SemanticStatus, TreeNode, TreeView

_CONFIG_ENTRY_POINT_GROUP = "omop.config"
"""Entry-point group every stack package registers its ``PackageConfigBase`` under.

Consulting it is what lets a ``[tools.*]`` section be rendered from its own schema.
Sensitivity is then read off the ``Sensitive()`` markers on that schema rather than
guessed at from field names, which is a guess this module used to make and no longer
makes anywhere.
"""
_ENDPOINT_FIELDS: dict[type[BaseModel], frozenset[str]] = {
    ProviderConfig: frozenset({"base_url"}),
}
"""Fields holding a free-form endpoint URL, masked with ``safe_endpoint`` on display.

``ProviderConfig`` rejects userinfo at validation and declares ``api_key``
``Sensitive()``, but nothing stops a credential riding in the query string
(``?api_key=...``), and that URL is an ordinary non-sensitive field. Keyed by model
type so this stays a statement about one known schema, rather than a guess about what
any field named ``base_url`` might contain.
"""
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
    ``[tools.*]`` sections are typed from the ``omop.config`` entry-point registry, so a
    package that registers a ``PackageConfigBase`` gets the same sensitivity and reference
    inspection without the caller doing anything. A caller may still pass resolved
    instances, which win over the registry. Editable candidates and persistence remain
    outside groundskeeping.

    A section with no usable schema is rendered by shape only -- see
    :meth:`_untyped_entry` for why that is the safe reading rather than the cautious one.
    """

    def snapshot(
        self,
        stack_config: StackConfig,
        *,
        config_path: str | Path | None = None,
        package_configs: Iterable[PackageConfigBase] = (),
        title: str = "Stack configuration",
    ) -> ConfiguratorSnapshot:
        typed, unavailable = self._resolve_package_configs(stack_config, package_configs)
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
            self._tool_section(stack_config, typed, unavailable),
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

    def _resolve_package_configs(
        self,
        stack_config: StackConfig,
        package_configs: Iterable[PackageConfigBase],
    ) -> tuple[dict[str, PackageConfigBase], dict[str, str]]:
        """Type the ``[tools.*]`` sections that have a schema available.

        Returns the typed instances by tool name, and a reason-by-tool-name for the
        sections whose registered class could not be used at all.

        The registry types the sections that are *present*; it does not add sections
        of its own. A package being installed says nothing about whether the config
        being inspected mentions it, and inventing an entry for every registered
        package would make the view a report on the environment rather than on the
        file. Passing an instance explicitly is still how a caller asks for a section
        the file does not have.

        Explicitly-passed instances also win outright: a caller may hold an
        already-resolved config carrying values that validating the section afresh
        would not reproduce. Everything else is validated out of its own section, the
        same way ``Resolver.resolve_package_config`` does it, absent section included.

        Nothing here is allowed to raise. A registered package can fail to import
        (missing extra, broken install, import-time error) or carry a section that no
        longer validates, and this view is most useful precisely when an environment
        is half-broken. Letting one bad entry point escape would take every other
        section on the screen down with it.
        """
        explicit = {type(package).tool_name: package for package in package_configs}
        registry = self._registered_config_classes()
        typed: dict[str, PackageConfigBase] = {}
        unavailable: dict[str, str] = {}
        for key in set(stack_config.tools) | set(explicit):
            package = explicit.get(key)
            if package is not None:
                typed[key] = package
                continue
            registered = registry.get(key)
            if registered is None:
                continue
            if isinstance(registered, str):
                unavailable[key] = registered
                continue
            try:
                section = stack_config.tools.get(key, {})
                typed[key] = registered.model_validate(section)
            except Exception as exc:  # noqa: BLE001 - a bad section must not break the view
                unavailable[key] = f"{type(exc).__name__}: {exc}"
        return typed, unavailable

    def _registered_config_classes(
        self,
    ) -> dict[str, type[PackageConfigBase] | str]:
        """Map tool name to the config class registered for it.

        An entry that fails to load maps to its failure text instead of a class, so
        the caller can report an unreadable section rather than silently lose it.
        Such an entry is keyed by its entry-point name, the two agreeing by
        convention; a loadable one is keyed by the ``tool_name`` the class itself
        declares, which is what the TOML section is actually named after.

        A distribution with unreadable metadata can take out the whole enumeration,
        which is why even that is caught.
        """
        try:
            found = tuple(entry_points(group=_CONFIG_ENTRY_POINT_GROUP))
        except Exception:  # noqa: BLE001 - broken metadata is not worth a traceback here
            return {}
        registered: dict[str, type[PackageConfigBase] | str] = {}
        for entry_point in found:
            try:
                config_class = entry_point.load()
            except Exception as exc:  # noqa: BLE001 - see _resolve_package_configs
                registered[entry_point.name] = f"{type(exc).__name__}: {exc}"
                continue
            registered[getattr(config_class, "tool_name", entry_point.name)] = config_class
        return registered

    def _tool_section(
        self,
        stack_config: StackConfig,
        typed: Mapping[str, PackageConfigBase],
        unavailable: Mapping[str, str],
    ) -> ConfigSectionView:
        children = []
        for key in sorted(set(stack_config.tools) | set(typed) | set(unavailable)):
            package = typed.get(key)
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
                self._untyped_entry(
                    key,
                    stack_config.tools.get(key, {}),
                    unavailable.get(key),
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
            if is_sensitive(info):
                fields[name] = RedactedValue()
                continue
            if name in _ENDPOINT_FIELDS.get(type(value), frozenset()):
                fields[name] = safe_endpoint(item)
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

    def _untyped_entry(
        self,
        key: str,
        section: Mapping[str, object],
        failure: str | None,
    ) -> ConfigSectionView:
        """
        Render the shape of a section with no usable schema, never its values.
        """
        notes = [
            f"No config class could be loaded for this section ({failure})."
            if failure is not None
            else "No config class is registered for this section.",
            ("Values are hidden. Register a PackageConfigBase under the "
            f"{_CONFIG_ENTRY_POINT_GROUP!r} entry-point group and mark secrets with "
            "Sensitive() to inspect them."),
        ]
        return ConfigSectionView(
            target=ConfigTarget(
                kind=ConfigTargetKind.TOOL,
                key=key,
                title=key,
                status=SemanticStatus.WARNING,
            ),
            fields={"keys": len(section)},
            notes=tuple(notes),
        )

    def _display_value(self, value: object) -> object:
        safe = self._redact_nested(value)
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
                    sensitive=is_sensitive(info),
                )
                for name, info in type(value).model_fields.items()
            }
        if isinstance(value, Mapping):
            return {str(name): self._redact_nested(item) for name, item in value.items()}
        if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
            return tuple(self._redact_nested(item) for item in value)
        if isinstance(value, set | frozenset):
            return tuple(self._redact_nested(item) for item in value)
        if isinstance(value, Enum):
            return value.value
        if isinstance(value, Path):
            return str(value)
        return value

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
