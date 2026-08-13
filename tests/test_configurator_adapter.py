from __future__ import annotations

import asyncio
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
    Sensitive,
    StackConfig,
    VectorStoreConfig,
)
from textual.app import App, ComposeResult
from textual.widgets import Tree

from groundskeeping.configurator import (
    ConfigDraft,
    ConfigReferenceStatus,
    ConfigReferenceView,
    ConfigTarget,
    ConfigTargetKind,
    ConfiguratorSnapshot,
    OAConfiguratorAdapter,
    RedactedValue,
)
from groundskeeping.contracts import SemanticStatus
from groundskeeping.widgets.configurator import ConfiguratorBrowser


class KnownToolConfig(PackageConfigBase):
    tool_name: ClassVar[str] = "known_tool"
    cdm_db: Annotated[str, RefTo(CDMDatabaseConfig)] = "cdm"
    api_token: Annotated[str | None, Sensitive()] = None


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
    assert unknown.target.status is SemanticStatus.WARNING
    assert unknown.fields["options"] == "1 entries"
    assert unknown.notes == (
        "Package schema unavailable; reference status is unknown.",
    )


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


def test_diff_redacts_sensitive_values() -> None:
    adapter = OAConfiguratorAdapter()
    target = ConfigTarget(
        kind=ConfigTargetKind.DATABASE,
        key="metadata",
        title="metadata",
    )
    diff = adapter.diff(
        target,
        original_fields={"url": "postgresql://old", "password": "old-secret"},
        candidate_fields={"url": "postgresql://new", "password": "new-secret"},
        sensitive_fields=frozenset({"password"}),
    )

    assert diff.changed
    password = next(entry for entry in diff.entries if entry.field == "password")
    assert isinstance(password.before, RedactedValue)
    assert isinstance(password.after, RedactedValue)
    assert "new-secret" not in repr(diff)


def test_config_draft_only_tracks_safe_changed_field_presence() -> None:
    target = ConfigTarget(
        kind=ConfigTargetKind.DATABASE,
        key="metadata",
        title="metadata",
    )
    draft = ConfigDraft(
        target=target,
        changed_fields=frozenset({"url", "password"}),
        expected_revision="abc",
    )

    assert draft.changed
    assert draft.changed_fields == frozenset({"url", "password"})
    assert "secret" not in repr(draft)
