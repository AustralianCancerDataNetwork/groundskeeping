# Configuration

`groundskeeping.configurator` presents `oa-configurator` stack configuration safely. It can
build snapshots, section views, safe drafts, redacted diffs, revision-aware apply intents, and
wizard-controller entry points.

Groundworkers can use this to show database resources and launch a setup wizard. Another
application might use the same pieces for model providers or local runtime paths.

## Inspection

[`OAConfiguratorAdapter`][groundskeeping.configurator.adapter.OAConfiguratorAdapter] is
structural: tests and demos can pass fakes, while real applications pass `StackConfig` and
`PackageConfigBase` instances from `oa-configurator`.

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
diff = adapter.diff(
    target,
    original_fields={"dsn": "postgresql://old"},
    candidate_fields={"dsn": "postgresql://new"},
    sensitive_fields=frozenset({"dsn"}),
)
```

## What it does not do

It does not write TOML. Persistence belongs to `oa-configurator` and to the application using
Groundskeeping. That separation protects comments, secrets, external edits, and local safety
rules.

Editable candidates still belong to application-owned controllers. `ConfigDraft` records the
safe target and changed-field presence, not raw field values. `ConfigApplyIntent` carries the
safe target, opaque apply token, expected revision, diff, and effects needed by a public
mutation API.

## Extending

Applications can add `ConfigResourceAdapter` implementations for resource types that need
better labels, choices, validation, verification, or post-apply effects.

`NativeConfigResourceAdapter` is the fallback for ordinary configuration sections. It is
intentionally plain: it offers display fields and validates nothing beyond the model layer
that `oa-configurator` will run during a real apply.

Resource adapters can also expose a `WizardController` for setup flows. Groundskeeping renders
the controller in a modal wizard; the adapter remains responsible for validation, branching,
stale-revision checks, and the final apply call.
