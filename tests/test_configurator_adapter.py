from __future__ import annotations

from dataclasses import dataclass

from groundskeeping.configurator import ConfigDraft, ConfigTarget, OAConfiguratorAdapter, RedactedValue


@dataclass
class Database:
    url: str
    password: str
    role: str


@dataclass
class Stack:
    path: str
    active_profile: str
    databases: dict[str, Database]
    resources: dict[str, dict[str, str]]
    profiles: dict[str, dict[str, str]]
    aliases: dict[str, str]


def test_snapshot_builds_read_only_sections_and_redacts_known_secrets() -> None:
    snapshot = OAConfiguratorAdapter().snapshot(
        Stack(
            path="/tmp/stack.toml",
            active_profile="tre",
            databases={
                "metadata": Database(
                    url="postgresql://example/metadata",
                    password="super-secret",
                    role="readonly",
                )
            },
            resources={"ollama": {"url": "http://ollama:11434"}},
            profiles={"tre": {"database": "metadata"}},
            aliases={"default-model": "snowflake-arctic-embed2"},
        )
    )

    assert snapshot.path == "/tmp/stack.toml"
    assert snapshot.profile == "tre"

    database_group = next(section for section in snapshot.sections if section.target.key == "database")
    metadata = database_group.children[0]

    assert metadata.fields["url"] == "postgresql://example/metadata"
    assert isinstance(metadata.fields["password"], RedactedValue)
    assert "super-secret" not in repr(snapshot)


def test_adapter_can_render_snapshot_as_tree_view() -> None:
    snapshot = OAConfiguratorAdapter().snapshot(
        Stack(
            path="/tmp/stack.toml",
            active_profile="local",
            databases={},
            resources={"model-server": {"kind": "ollama"}},
            profiles={},
            aliases={},
        )
    )

    view = OAConfiguratorAdapter().as_tree_view(snapshot)

    assert view.title == "Stack configuration"
    assert view.rows[0].label == "Resources"


def test_diff_redacts_sensitive_values() -> None:
    adapter = OAConfiguratorAdapter()
    target = ConfigTarget(kind="database", key="metadata", title="metadata")
    draft = ConfigDraft(
        target=target,
        original_fields={"url": "postgresql://old", "password": "old-secret"},
        candidate_fields={"url": "postgresql://new", "password": "new-secret"},
        expected_revision="abc",
    )

    diff = adapter.diff(draft, sensitive_fields=frozenset({"password"}))

    assert diff.changed
    password = next(entry for entry in diff.entries if entry.field == "password")
    assert isinstance(password.before, RedactedValue)
    assert isinstance(password.after, RedactedValue)
    assert "new-secret" not in repr(diff)
