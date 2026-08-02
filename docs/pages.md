# Pages and the Workbench

Pages are ordinary Textual widgets owned by the application using Groundskeeping. The shell
mounts them once, activates and deactivates them as the operator moves between tabs, and
preserves page-local state.

A page receives a narrow [`PageContext`][groundskeeping.contracts.pages.PageContext]. It does
not receive the whole app.

## The workbench surface

The default page surface is the workbench:

- flat section navigation or a hierarchical catalogue on the left;
- rows or tree content on the upper right; and
- selected detail on the lower right.

Use `SectionNavigation` for peer areas such as Database, Embeddings, and Runtime. Use
`CatalogueNavigation` when hierarchy is the point, such as a provider with nested models or an
evaluation run with nested artefacts.

Translate domain objects before they reach the workbench. The workbench understands
`SectionItem`, `CatalogueItem`, `TableView`, `TreeView`, and friends; it does not need to know
what a Groundworkers resource or `cava-nlp-shard` evaluation object is.

Use `OperatorAppSpec.workbench_labels` to rename shared pane chrome such as the result and
detail panel labels. Page-owned titles still live on navigation and view contracts: for
example, `SectionNavigation.title` names the left pane for a specific page, and
`TableView.title` names the current result content.

## Routing

`PageRoute` is the navigation identity for one page: a `key`, an operator-facing `label`, and
a `purpose` line rendered beside the heading. `PageRegistry` validates that keys are unique
and that at least one route exists, and `OperatorAppSpec.validate` additionally rejects
duplicate page factories and unknown `default_page` keys.

Validation happens at construction, not at first navigation, so a misconfigured app fails at
startup rather than when an operator clicks a tab.

## Page lifecycle

| Method | When the shell calls it |
|---|---|
| `activate` | The page becomes the visible tab |
| `deactivate` | The operator moves to a different tab |
| `build_navigation` | Each time the page is rendered, to populate the left pane |
| `landing_view` | Each time the page is rendered, to populate the upper-right pane |
| `navigation_selected` | A section or catalogue item is selected |
| `action_selected` | A command button in the current view is pressed |
| `row_highlighted` | A result-table row is highlighted |
| `row_selected` | A result-table row is selected |

Row events return to the active page. The workbench renders generic models; the page decides
what a highlighted row means.

Detail panes can render `TextView`, `KeyValueView`, or `TableView`. Use a detail `TableView`
when the selected item has its own repeated data, such as available LLM models for a provider.

If `landing_view` raises, the shell catches the exception and renders an `EmptyView`
explaining that the page could not be rendered. A page that cannot build its landing content
degrades to a message instead of taking down the app.

## Setup pages

A setup page should answer a practical operator question: "is this environment ready for the
work I am about to run?"

The page normally lives in the application using Groundskeeping. It can call whatever services
that application already has for config, credentials, model providers, database checks, or
runtime health.

A good setup page usually has:

- a flat list of setup areas, such as config, database, runtime, model server, paths, or
  credentials;
- a landing `TreeView` summarising overall readiness;
- a `TableView` for repeated checks where scanning matters;
- `KeyValueView` detail for the selected check;
- one or two safe verification actions; and
- an operation policy that describes effects in the application's own vocabulary.

Start read-only. A **Test connection** or **Refresh status** button is often enough to prove
the page shape before you add durable writes.

When setup requires guided edits, expose a `ViewAction` from the current view and open a
wizard with `PageContext.open_wizard`. The page still owns what the wizard means;
Groundskeeping only renders the navigation, fields, review state, and final result.
