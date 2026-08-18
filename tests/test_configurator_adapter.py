from __future__ import annotations

import asyncio
from importlib.metadata import EntryPoint
from pathlib import Path
from typing import Annotated, ClassVar

from oa_configurator import (
    CDMDatabaseConfig,
    ConnectionConfig,
    GenericDatabaseConfig,
    LoggingConfig,
    ModelConfig,
    PackageConfigBase,
    ProviderConfig,
    RefTo,
    Secret,
    Sensitive,
    StackConfig,
    VectorStoreConfig,
    assert_no_sensitive_values_leak,
)
from textual.app import App, ComposeResult
from textual.widgets import Tree

from groundskeeping.configurator import (
    ConfigReferenceStatus,
    ConfigReferenceView,
    ConfigTargetKind,
    ConfiguratorSnapshot,
    OAConfiguratorAdapter,
    RedactedValue,
)
from groundskeeping.configurator import adapter as adapter_module
from groundskeeping.contracts import SemanticStatus
from groundskeeping.widgets.configurator import ConfiguratorBrowser


class KnownToolConfig(PackageConfigBase):
    tool_name: ClassVar[str] = "known_tool"
    cdm_db: Annotated[str, RefTo(CDMDatabaseConfig)] = "cdm"
    api_token: Annotated[str | None, Sensitive()] = None


class RegistryToolConfig(PackageConfigBase):
    """Stands in for a package that registers itself under ``omop.config``.

    Resolved through a genuine ``EntryPoint`` rather than handed to ``snapshot()``,
    which is the whole point of the registry path. groundskeeping cannot depend on a
    package that registers one for real without inverting the stack's dependency
    direction, so the entry point is pointed at this module instead.
    """

    tool_name: ClassVar[str] = "registry_tool"
    cdm_db: Annotated[str, RefTo(CDMDatabaseConfig)] = "cdm"
    api_token: Secret = None
    # Named like a secret, declared like anything else. Rendered in full, on purpose.
    key: str = "not-declared-sensitive"


def _registry_of(*classes: type[PackageConfigBase]):
    """Patch-in for ``entry_points``, yielding real entry points for *classes*."""
    points = tuple(
        EntryPoint(
            name=config_class.tool_name,
            value=f"{__name__}:{config_class.__name__}",
            group="omop.config",
        )
        for config_class in classes
    )
    return lambda group: points if group == "omop.config" else ()


def _full_stack(*, canary: str = "secret-canary") -> StackConfig:
    stack = StackConfig(
        connections={
            "primary": ConnectionConfig(
                dialect="postgresql+psycopg",
                host="db.example",
                user="analyst",
                password=canary,
                database_name="omop",
            ),
            "vocab": ConnectionConfig(
                dialect="postgresql+psycopg",
                host="vocab.example",
                password=f"vocab-{canary}",
                database_name="vocab",
            ),
        },
        databases={
            "cdm": CDMDatabaseConfig(
                connection="primary",
                schema_name="omop",
                vocab_connection="vocab",
                vocab_schema="vocabulary",
                results_schema="results",
            ),
            "vector_db": GenericDatabaseConfig(
                connection="primary",
                schema_name="embeddings",
            ),
        },
        providers={
            "local": ProviderConfig(
                provider="ollama",
                base_url="http://localhost:11434",
                api_key=f"provider-{canary}",
            )
        },
        models={
            "embed": ModelConfig(
                provider="local",
                model="nomic-embed",
                embeddings=True,
                configuration={"headers": {"api_key": f"nested-{canary}"}},
            )
        },
        vector_stores={
            "vectors": VectorStoreConfig(
                backend_type="pgvector",
                database="vector_db",
                configuration={"auth": {"password": f"vector-{canary}"}},
            )
        },
        tools={
            "known_tool": {"cdm_db": "cdm", "api_token": f"tool-{canary}"},
            "unknown_tool": {
                "endpoint": "http://service.example",
                "options": {"credentials": {"password": f"unknown-{canary}"}},
            },
        },
        logging=LoggingConfig(level="INFO", loggers={"sqlalchemy.engine": "WARNING"}),
    )
    stack.bind_loaded_path(Path("/tmp/stack.toml"))
    return stack


def _section(snapshot: ConfiguratorSnapshot, kind: ConfigTargetKind):
    return next(section for section in snapshot.sections if section.target.kind is kind)


def _child(snapshot: ConfiguratorSnapshot, kind: ConfigTargetKind, key: str):
    return next(child for child in _section(snapshot, kind).children if child.target.key == key)


def test_snapshot_renders_all_sections_in_stable_order() -> None:
    snapshot = OAConfiguratorAdapter().snapshot(
        _full_stack(),
        package_configs=(KnownToolConfig(cdm_db="cdm", api_token="typed-secret"),),
    )

    assert snapshot.path == str(Path("/tmp/stack.toml").resolve())
    assert tuple(section.target.kind for section in snapshot.sections) == tuple(
        ConfigTargetKind
    )
    assert tuple(section.target.title for section in snapshot.sections) == (
        "Connections",
        "Databases",
        "Providers",
        "Models",
        "Vector stores",
        "Tools",
        "Logging",
    )


def test_empty_sections_and_default_logging_remain_visible() -> None:
    snapshot = OAConfiguratorAdapter().snapshot(StackConfig.for_session())

    assert len(snapshot.sections) == 7
    assert all(
        section.target.status is SemanticStatus.IDLE
        for section in snapshot.sections[:-1]
    )
    logging = _section(snapshot, ConfigTargetKind.LOGGING)
    assert logging.target.status is SemanticStatus.IDLE
    assert logging.notes == ("Using default logging settings.",)


def test_database_views_follow_the_concrete_database_kind() -> None:
    snapshot = OAConfiguratorAdapter().snapshot(_full_stack())
    generic = _child(snapshot, ConfigTargetKind.DATABASE, "vector_db")
    cdm = _child(snapshot, ConfigTargetKind.DATABASE, "cdm")

    assert generic.fields["kind"] == "generic"
    assert "vocab_connection" not in generic.fields
    assert cdm.fields["kind"] == "cdm"
    assert cdm.fields["vocab_schema"] == "vocabulary"
    vocab = cdm.fields["vocab_connection"]
    assert isinstance(vocab, ConfigReferenceView)
    assert vocab.section is ConfigTargetKind.CONNECTION
    assert vocab.name == "vocab"
    assert vocab.status is ConfigReferenceStatus.RESOLVED


def test_missing_reference_is_reported_without_hiding_the_entry() -> None:
    stack = StackConfig.for_session()
    stack.models["broken"] = ModelConfig(provider="missing", model="chat")

    snapshot = OAConfiguratorAdapter().snapshot(stack)
    model = _child(snapshot, ConfigTargetKind.MODEL, "broken")
    reference = model.fields["provider"]

    assert model.target.status is SemanticStatus.ERROR
    assert isinstance(reference, ConfigReferenceView)
    assert reference.status is ConfigReferenceStatus.MISSING
    assert reference.section is ConfigTargetKind.PROVIDER
    assert reference.name == "missing"
    assert "missing provider" in model.notes[0]


def test_wrong_database_kind_is_reported() -> None:
    stack = StackConfig.for_session(
        connections={"db": ConnectionConfig(dialect="sqlite", database_name=":memory:")},
        databases={"cdm": CDMDatabaseConfig(connection="db")},
    )
    stack.vector_stores["vectors"] = VectorStoreConfig(
        backend_type="pgvector",
        database="cdm",
    )

    snapshot = OAConfiguratorAdapter().snapshot(stack)
    vector_store = _child(snapshot, ConfigTargetKind.VECTOR_STORE, "vectors")
    reference = vector_store.fields["database"]

    assert vector_store.target.status is SemanticStatus.ERROR
    assert isinstance(reference, ConfigReferenceView)
    assert reference.status is ConfigReferenceStatus.WRONG_KIND
    assert reference.expected_type == "GenericDatabaseConfig"
    assert reference.actual_type == "CDMDatabaseConfig"


def test_known_and_unknown_tools_are_distinguished() -> None:
    snapshot = OAConfiguratorAdapter().snapshot(
        _full_stack(),
        package_configs=(KnownToolConfig(cdm_db="cdm", api_token="typed-secret"),),
    )
    known = _child(snapshot, ConfigTargetKind.TOOL, "known_tool")
    unknown = _child(snapshot, ConfigTargetKind.TOOL, "unknown_tool")

    assert known.target.status is SemanticStatus.OK
    assert isinstance(known.fields["api_token"], RedactedValue)
    assert isinstance(known.fields["cdm_db"], ConfigReferenceView)
    assert known.notes == ()
    # Behaviour change: an untyped section is now rendered by shape only. It used
    # to print its values, redacting the ones whose names looked secret-ish.
    assert unknown.target.status is SemanticStatus.WARNING
    assert unknown.fields == {"keys": 2}
    assert "endpoint" not in unknown.fields
    assert unknown.notes[0] == "No config class is registered for this section."


def test_secrets_never_enter_snapshot_tree_or_rendered_widget() -> None:
    async def run() -> None:
        canary = "never-render-this-canary"
        snapshot = OAConfiguratorAdapter().snapshot(
            _full_stack(canary=canary),
            package_configs=(
                KnownToolConfig(cdm_db="cdm", api_token=f"typed-{canary}"),
            ),
        )
        tree_view = OAConfiguratorAdapter().as_tree_view(snapshot)

        assert canary not in repr(snapshot)
        assert canary not in repr(tree_view)

        class BrowserApp(App[None]):
            def compose(self) -> ComposeResult:
                yield ConfiguratorBrowser(snapshot)

        app = BrowserApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            tree = app.query_one(Tree)
            pending = [tree.root]
            rendered_labels: list[str] = []
            while pending:
                node = pending.pop()
                rendered_labels.append(str(node.label))
                pending.extend(node.children)

            assert canary not in "\n".join(rendered_labels)

    asyncio.run(run())


def test_config_path_override_is_read_only_display_metadata(tmp_path: Path) -> None:
    explicit = tmp_path / "inspected.toml"
    snapshot = OAConfiguratorAdapter().snapshot(
        StackConfig.for_session(),
        config_path=explicit,
    )
    view = OAConfiguratorAdapter().as_tree_view(snapshot)

    assert snapshot.path == str(explicit)
    assert view.message == f"path: {explicit}"
    assert "profile" not in view.message


def test_target_kinds_are_the_oa_configurator_1_x_sections() -> None:
    assert tuple(ConfigTargetKind) == (
        ConfigTargetKind.CONNECTION,
        ConfigTargetKind.DATABASE,
        ConfigTargetKind.PROVIDER,
        ConfigTargetKind.MODEL,
        ConfigTargetKind.VECTOR_STORE,
        ConfigTargetKind.TOOL,
        ConfigTargetKind.LOGGING,
    )


def test_registered_package_is_typed_without_the_caller_passing_it(monkeypatch) -> None:
    """The registry, not the caller, is what makes a tool section typed.

    Every package in the stack already registers a ``PackageConfigBase`` under
    ``omop.config``; before this, only the one config a caller happened to hand over
    was read from its schema and the rest were rendered by guesswork.
    """
    monkeypatch.setattr(
        adapter_module, "entry_points", _registry_of(RegistryToolConfig)
    )
    stack = _full_stack()
    stack.tools["registry_tool"] = {"cdm_db": "cdm", "api_token": "registry-secret"}

    snapshot = OAConfiguratorAdapter().snapshot(stack)  # no package_configs
    section = _child(snapshot, ConfigTargetKind.TOOL, "registry_tool")

    assert section.target.status is SemanticStatus.OK
    assert isinstance(section.fields["cdm_db"], ConfigReferenceView)
    assert section.fields["cdm_db"].status is ConfigReferenceStatus.RESOLVED
    assert isinstance(section.fields["api_token"], RedactedValue)
    assert "registry-secret" not in repr(snapshot)


def test_explicitly_passed_config_wins_over_the_registry(monkeypatch) -> None:
    """A caller may hold a resolved instance the class default would not reproduce."""
    monkeypatch.setattr(
        adapter_module, "entry_points", _registry_of(RegistryToolConfig)
    )
    stack = _full_stack()
    stack.tools["registry_tool"] = {"cdm_db": "cdm", "key": "from-the-file"}

    snapshot = OAConfiguratorAdapter().snapshot(
        stack,
        package_configs=(RegistryToolConfig(cdm_db="cdm", key="from-the-caller"),),
    )
    section = _child(snapshot, ConfigTargetKind.TOOL, "registry_tool")

    assert section.fields["key"] == "from-the-caller"


def test_only_declared_secrets_are_redacted(monkeypatch) -> None:
    """``Sensitive()`` is the whole test. A secret-ish *name* no longer counts.

    Deliberate behaviour change: ``key`` used to be redacted because a word list said
    so. A package that wants it hidden declares it, which is a contract the type system
    can enforce and a word list never could.
    """
    monkeypatch.setattr(
        adapter_module, "entry_points", _registry_of(RegistryToolConfig)
    )
    stack = _full_stack()
    stack.tools["registry_tool"] = {"api_token": "declared", "key": "undeclared"}

    snapshot = OAConfiguratorAdapter().snapshot(stack)
    section = _child(snapshot, ConfigTargetKind.TOOL, "registry_tool")

    assert isinstance(section.fields["api_token"], RedactedValue)
    assert section.fields["key"] == "undeclared"


def test_config_class_that_fails_to_import_degrades_to_the_placeholder(
    monkeypatch,
) -> None:
    """A broken install is exactly when someone opens the inspector.

    Modelled on a failure seen in the wild: a package registered under ``omop.config``
    whose module imports a name its pinned oa-configurator no longer exports.
    """

    class _UnimportableEntryPoint:
        name = "unknown_tool"

        def load(self):
            raise ImportError(
                "cannot import name 'ResourceSpec' from 'oa_configurator'"
            )

    monkeypatch.setattr(
        adapter_module, "entry_points", lambda group: (_UnimportableEntryPoint(),)
    )
    canary = "import-failure-canary"

    snapshot = OAConfiguratorAdapter().snapshot(_full_stack(canary=canary))
    section = _child(snapshot, ConfigTargetKind.TOOL, "unknown_tool")

    assert section.target.status is SemanticStatus.WARNING
    assert section.fields == {"keys": 2}
    assert "ImportError" in section.notes[0]
    assert canary not in repr(snapshot)
    assert canary not in repr(OAConfiguratorAdapter().as_tree_view(snapshot))


def test_unreadable_entry_point_metadata_does_not_break_the_view(monkeypatch) -> None:
    """One unreadable distribution must not take every other section down with it."""

    def _explode(group):
        raise ValueError("invalid distribution metadata")

    monkeypatch.setattr(adapter_module, "entry_points", _explode)

    snapshot = OAConfiguratorAdapter().snapshot(_full_stack())

    assert len(snapshot.sections) == 7
    assert _child(snapshot, ConfigTargetKind.CONNECTION, "primary").fields["host"] == (
        "db.example"
    )


def test_untyped_section_shows_its_shape_and_none_of_its_values() -> None:
    """No schema means no basis for showing anything but the shape."""
    canary = "untyped-section-canary"

    snapshot = OAConfiguratorAdapter().snapshot(_full_stack(canary=canary))
    section = _child(snapshot, ConfigTargetKind.TOOL, "unknown_tool")
    tree_view = OAConfiguratorAdapter().as_tree_view(snapshot)

    assert section.fields == {"keys": 2}
    assert canary not in repr(snapshot)
    assert canary not in repr(tree_view)
    # Not just the secret: the non-secret values are withheld too, because without
    # a schema there is nothing to tell the two apart.
    assert "http://service.example" not in repr(snapshot)


def test_provider_base_url_is_masked_through_safe_endpoint() -> None:
    """``base_url`` is an ordinary field, and a credential can still ride in its query.

    The schema rejects userinfo and declares ``api_key`` sensitive, so this query
    string was the one way left for a secret to reach the screen from a provider.
    """
    stack = StackConfig(
        providers={
            "azure": ProviderConfig(
                provider="openai",
                base_url="https://azure.example/v1?api-version=2024-02-01&api_key=sk-canary",
            )
        }
    )

    snapshot = OAConfiguratorAdapter().snapshot(stack)
    provider = _child(snapshot, ConfigTargetKind.PROVIDER, "azure")

    assert provider.fields["base_url"] == (
        "https://azure.example/v1?api-version=***&api_key=***"
    )
    assert "sk-canary" not in repr(snapshot)
    assert "sk-canary" not in repr(OAConfiguratorAdapter().as_tree_view(snapshot))


def test_declared_secrets_never_reach_a_rendered_snapshot() -> None:
    """oa-configurator's own leak check, run over what this adapter renders."""
    stack = StackConfig(
        connections={
            "primary": ConnectionConfig(
                dialect="postgresql+psycopg",
                host="db.example",
                user="analyst",
                password="connection-leak-canary",
                database_name="omop",
            )
        },
        providers={
            "azure": ProviderConfig(
                provider="openai",
                base_url="https://azure.example/v1",
                api_key="provider-leak-canary",
            )
        },
    )
    adapter = OAConfiguratorAdapter()
    snapshot = adapter.snapshot(stack)

    assert_no_sensitive_values_leak(stack, snapshot)
    assert_no_sensitive_values_leak(stack, adapter.as_tree_view(snapshot))
