from __future__ import annotations

from dataclasses import dataclass

from groundskeeping.configurator import (
    ConfigDraft,
    ConfigTarget,
    ConfigTargetKind,
    OAConfiguratorAdapter,
    RedactedValue,
)


@dataclass
class Database:
    url: str
    password: str
    role: str


@dataclass
class Stack:
    loaded_path: str
    connections: dict[str, dict[str, str]]
    databases: dict[str, Database]
    providers: dict[str, dict[str, str]]
    models: dict[str, dict[str, str]]
    vector_stores: dict[str, dict[str, str]]
    tools: dict[str, dict[str, str]]
    logging: dict[str, str]


def _stack(
    *,
    connections: dict[str, dict[str, str]] | None = None,
    databases: dict[str, Database] | None = None,
    providers: dict[str, dict[str, str]] | None = None,
    models: dict[str, dict[str, str]] | None = None,
) -> Stack:
    return Stack(
        loaded_path="/tmp/stack.toml",
        connections=connections or {},
        databases=databases or {},
        providers=providers or {},
        models=models or {},
        vector_stores={},
        tools={},
        logging={},
    )


def test_snapshot_builds_read_only_sections_and_redacts_known_secrets() -> None:
    snapshot = OAConfiguratorAdapter().snapshot(
        _stack(
            databases={
                "metadata": Database(
                    url="postgresql://example/metadata",
                    password="super-secret",
                    role="readonly",
                )
            },
            providers={"ollama": {"provider": "ollama"}},
            models={"embed": {"provider": "ollama", "model": "nomic-embed"}},
        )
    )

    assert snapshot.path == "/tmp/stack.toml"
    assert not hasattr(snapshot, "profile")

    database_group = next(section for section in snapshot.sections if section.target.key == "database")
    metadata = database_group.children[0]

    assert metadata.fields["url"] == "postgresql://example/metadata"
    assert isinstance(metadata.fields["password"], RedactedValue)
    assert "super-secret" not in repr(snapshot)


def test_adapter_can_render_snapshot_as_tree_view() -> None:
    snapshot = OAConfiguratorAdapter().snapshot(
        _stack(
            connections={"metadata": {"dialect": "sqlite"}},
        )
    )

    view = OAConfiguratorAdapter().as_tree_view(snapshot)

    assert view.title == "Stack configuration"
    assert view.rows[0].label == "Connections"
    assert view.message is not None
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
