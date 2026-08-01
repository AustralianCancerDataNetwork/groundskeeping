# Configuration

`groundskeeping.configurator` understands the public shape of `oa-configurator` stack
configuration well enough to inspect and present it safely. It can build snapshots, section
views, drafts, redacted diffs, and apply intents.

## Inspection

[`OAConfiguratorAdapter`][groundskeeping.configurator.adapter.OAConfiguratorAdapter] is
deliberately structural: tests and demos can pass fakes, while real consumers pass
`StackConfig` and `PackageConfigBase` instances from `oa-configurator`.

```python
from groundskeeping.configurator import OAConfiguratorAdapter

adapter = OAConfiguratorAdapter()
snapshot = adapter.snapshot(stack_config, config_path="stack.toml")
tree_view = adapter.as_tree_view(snapshot)
```

`snapshot` groups databases, resources, profiles, aliases, and package configs into
`ConfigSectionView` trees. `as_tree_view` converts a snapshot into a `TreeView` the workbench
can render directly.

## Redaction

Field names in `{"password", "secret", "token", "api_key"}` are replaced with `RedactedValue`
before they leave the adapter. Non-scalar values are summarised — `"3 entries"`, `"5 items"`,
or the type name — rather than expanded, so a nested credential structure cannot leak through
a rendered section.

`diff` builds a redacted structural diff for confirmation surfaces. An entry is marked
sensitive when the field is named in `sensitive_fields` or when either side is already a
`RedactedValue`; both sides are then replaced before the diff is returned.

```python
diff = adapter.diff(draft, sensitive_fields=frozenset({"dsn"}))
```

## What it does not do

It does not write TOML. Persistence belongs to the public `oa-configurator` mutation API and
to the consumer's operation policy. That separation protects comments, secrets, external
edits, and tenant-specific safety rules.

Editable drafts and persistence are intentionally left for a later phase that can use a public
revision-aware mutation API.

## Extending

Consumer applications can add `ConfigResourceAdapter` implementations for resource types that
need better labels, choices, validation, verification, or post-apply effects.

`NativeConfigResourceAdapter` is the fallback for ordinary configuration sections. It is
intentionally plain: it offers display fields and validates nothing beyond the model layer
that `oa-configurator` will run during a real apply.
