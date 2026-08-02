# Setup Wizards

Groundskeeping 0.2 adds a reusable setup-wizard surface for configuration flows that need
more guidance than a single action form.

The split is intentional:

- `groundskeeping.contracts.wizards` defines Textual-free wizard state, steps, review data,
  transitions, and results;
- `groundskeeping.widgets.WizardScreen` renders one step at a time; and
- the consumer owns the `WizardController`, including candidate state, validation, branching,
  revision checks, and apply semantics.

That keeps the shell reusable while still giving applications enough room to interact with
real configuration systems such as `oa-configurator`.

## Flow shape

A controller returns a `WizardSnapshot` from `start()`, then receives submitted field values
through `submit()`. Each transition returns the next render-safe snapshot plus any validation
issues. The shell does not copy secrets into its own state.

```python
from groundskeeping.contracts import WizardController

class DatabaseWizard:
    def start(self):
        ...

    def submit(self, values):
        ...

    def back(self):
        ...

    def review(self):
        ...

    def apply(self):
        ...

    def cancel(self):
        ...
```

Pages open a wizard through their `PageContext`:

```python
def action_selected(self, action_key, context):
    if action_key == "database.configure":
        context.open_wizard(DatabaseWizard(...))
```

## Steps

The initial contracts cover three step types:

- `ChoiceStep` for branch decisions such as reuse/create;
- `FormStep` for typed fields described with `FieldSpec`; and
- `ReviewStep` for redacted confirmation before apply.

`FieldSpec` supports text, integer, decimal, boolean, choice, existing path, output path,
secret, and multiline fields. It also carries presentation metadata such as placeholder text,
help text, disabled/read-only state, and secret behaviour.

## Secrets and revisions

Real candidate values belong in the controller. Snapshots should carry only values needed to
render the current step, and secret fields should be omitted or represented with redacted
display values.

Apply methods should carry an opaque expected-revision token from the start of the wizard to
the final mutation request. If the underlying config changed while the operator was editing,
return `WizardResultStatus.CONFLICTED` and refresh the relevant page instead of overwriting.

## Demo

Run the demo and open the **Configuration** page:

```bash
uv run groundskeeping
```

The **Configure database** action opens a small branching wizard that proves reuse/create,
choice/text/boolean/secret/multiline fields, validation, back navigation, cancel, redacted
review, apply, and stale-revision conflict handling.
