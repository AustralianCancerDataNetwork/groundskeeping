# Pages and the Workbench

Pages are owned by the consumer and are ordinary Textual widgets. The shell mounts them once,
activates and deactivates them as the operator moves between tabs, and preserves page-local
state. A page receives a narrow [`PageContext`][groundskeeping.contracts.pages.PageContext];
it does not receive the whole app.

## The workbench surface

The default page surface is the workbench:

- flat section navigation or a hierarchical catalogue on the left;
- rows or tree content on the upper right; and
- selected detail on the lower right.

Pages return `SectionNavigation` for flat peer areas and `CatalogueNavigation` for genuinely
hierarchical content. The workbench renders these as an option list and a tree respectively.
Domain objects should be translated before they reach either navigation model or a surface
view.

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

Row events return to the active page through the workbench surface rather than being handled
by the widget directly. That keeps the workbench generic: it renders normalized models and
routes interaction back to whichever page owns the current content.

If `landing_view` raises, the shell catches the exception and renders an `EmptyView`
explaining that the page could not be rendered. A page that cannot build its landing content
degrades to a message instead of taking down the app.

## Setup pages

A setup page should answer a concrete operator question: "can this environment do the work I
am about to ask of it?"

The page should normally live in the consumer package and use consumer services to inspect the
environment. `groundskeeping` supplies the rendering and action contracts; it does not know
what "ready" means for any particular application.

A good setup page usually has:

- a flat list of setup areas, such as config, database, runtime, model server, paths, or
  credentials;
- a landing `TreeView` summarising overall readiness;
- a `TableView` for repeated checks where scanning matters;
- `KeyValueView` detail for the selected check;
- one or two safe verification actions; and
- an operation policy that describes effects in the consumer's own vocabulary.

Start read-only. Verification actions are a good first step because they exercise the shell,
action contracts, progress reporting, and failure presentation without taking ownership of
durable setup changes too early.

When setup requires guided edits, expose a `ViewAction` from the current view and open a
consumer-owned wizard with `PageContext.open_wizard`. The page still owns what the wizard
means; Groundskeeping only renders the navigation, fields, review state, and final result.
