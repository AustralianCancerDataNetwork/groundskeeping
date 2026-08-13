# Configuration inspection

`groundskeeping.configurator` turns an `oa-configurator` 1.x stack into presentation-safe views for an operator interface. Groundskeeping supports oa-configurator 1.1 and later releases in the 1.x series.

## What an analyst sees

The configuration browser presents the seven current parts of a stack in a stable order:

1. connections;
2. databases;
3. providers;
4. models;
5. vector stores;
6. package-specific tools; and
7. logging.

Empty sections remain visible, so an analyst can distinguish “not configured” from a section the application forgot to inspect. Default logging is marked as such. The source path may be shown to help the analyst identify which configuration is open, but it is display metadata only and does not make the file writable through groundskeeping.

References are shown as the destination section and name, together with one of three states:

- **resolved** means the named entry exists with the required type;
- **missing** means no entry with that name exists in the destination section; and
- **wrong kind** means an entry exists, but its concrete type cannot be used by that field—for example, a vector store pointing to a CDM database instead of a generic database.

The current stack model has no profile, resource-alias, or active-profile layer. Applications pass the effective `StackConfig` they want the operator to inspect.

## Use it in an application

Pass the current `StackConfig` to `snapshot()`, then render the returned snapshot directly or convert it to the shared `TreeView`:

```python
from groundskeeping.configurator import OAConfiguratorAdapter

adapter = OAConfiguratorAdapter()
snapshot = adapter.snapshot(stack_config)
tree_view = adapter.as_tree_view(snapshot)
```

For a stack loaded from disk, `snapshot.path` comes from `StackConfig.loaded_path`. An application inspecting a candidate from another source can provide an explicit display path:

```python
snapshot = adapter.snapshot(candidate, config_path="/review/proposed.toml")
```

The adapter walks the public fields on oa-configurator's concrete models. A generic database therefore shows only generic database fields, while a CDM database also shows its vocabulary connection and vocabulary/results schemas.

### Give tool sections a schema

`StackConfig.tools` contains untyped dictionaries because package schemas are discovered at runtime. If your application has resolved package configuration instances, pass them to the adapter so their field metadata and `RefTo` declarations can be inspected:

```python
snapshot = adapter.snapshot(
    stack_config,
    package_configs=(my_package_config,),
)
```

Without a matching package instance, the tool remains visible but is marked **Package schema unavailable**. Groundskeeping redacts conservatively and shows its ordinary values, but does not claim that references are valid when it does not know which fields are references.

## Redaction guarantees

For typed models, fields marked `Sensitive` by oa-configurator are replaced with `RedactedValue` before a `ConfigSectionView` is created. For untyped tool dictionaries and nested free-form configuration, conservative secret names such as `password`, `api_key`, `secret`, and `token` are redacted recursively. Collections are summarized only after this redaction pass.

Snapshots, tree nodes, widget labels, notes, diffs, and repr output therefore contain redaction markers rather than raw known secrets. Applications should still avoid putting credentials under misleading, non-secret key names in free-form dictionaries; without schema metadata or a recognizable key, groundskeeping cannot infer that an arbitrary value is sensitive.

`diff()` applies the same presentation boundary to confirmation views. Name sensitive fields explicitly when the values do not already carry a `RedactedValue`:

```python
diff = adapter.diff(
    target,
    original_fields={"dsn": "postgresql://old"},
    candidate_fields={"dsn": "postgresql://new"},
    sensitive_fields=frozenset({"dsn"}),
)
```

## Ownership boundary

Groundskeeping inspects and presents configuration; it does not interpret package policy or write TOML. Candidate construction, oa-configurator validation, persistence, revision checks, and application restart policy stay with the application and its configuration provider.

`ConfigDraft` records only the target and the presence of changed fields, never submitted values. `ConfigApplyIntent` carries an opaque apply token, expected revision, redacted diff, and presentation-safe effects. This keeps the UI state useful without moving real candidate objects or secrets into groundskeeping.

Applications can implement `ConfigResourceAdapter` when a target needs domain-specific labels, fields, validation, verification, or post-apply effects. `NativeConfigResourceAdapter` remains the plain fallback for targets without richer application behavior.
