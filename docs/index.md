# groundskeeping

`groundskeeping` is a reusable Textual shell for tools that help people inspect, configure, and care for a working environment. It supplies a consistent workbench, guided configuration flows, safe actions, and telemetry presentation. Each consuming application supplies the domain behavior and language its users need.

## Choose your path

| If you are… | Start here | You will learn… |
|---|---|---|
| An analyst setting up or checking an environment | [Using a Groundskeeping app](operator-guide.md) | How to navigate the workbench, interpret status, review a configuration plan, and respond to apply results. |
| A developer adding Groundskeeping to an application | [Developer quickstart](quickstart.md) | How to register a page, supply view models, and run the shell. |
| A developer adding configuration inspection or writes | [Configuration](configuration.md) | How to inspect an oa-configurator stack and implement the provider-neutral mutation contract. |
| A developer upgrading from 0.3 | [Migrating to 1.0](migration-1.0.md) | Which provisional configuration APIs were removed and how the stable contracts differ. |

## What the package provides

| Area | Groundskeeping provides | Your application provides |
|---|---|---|
| [Pages and workbench](pages.md) | Tabs, navigation, result and detail panes, generic view models | Production pages, application presenters, and useful copy |
| [Actions and jobs](actions.md) | Field parsing, redaction, policy gates, progress, cancellation, in-process job tracking | Runners, safety policy, durable queue semantics, and recovery behavior |
| [Setup wizards](wizards.md) | Step rendering, Back/Next/Review/Apply/Cancel mechanics, safe snapshots | Workflow wording and, for configuration, a mutation provider |
| [Configuration](configuration.md) | Typed inspection and a safe generic wizard controller | Validation, private candidates, reference policy, revision checks, and persistence |
| [Telemetry](telemetry.md) | Normalized infrastructure metrics, sampling, and reusable widgets | Domain metrics, collectors that require application state, and interpretation |

## Install and try the demo

Groundskeeping requires Python 3.12 or newer.

```bash
uv add groundskeeping
uv run groundskeeping
```

The demo is self-contained. Open **Configuration**, select **Configure database**, and walk through the fake write flow to see branching, secret handling, review, and apply behavior without changing a file.

## Design boundary

Groundskeeping owns the reusable interaction model. It does not own an application's database rules, model calls, queue records, or configuration persistence. Keeping those responsibilities behind application services makes the shell useful across Groundworkers, `cava-nlp-shard`, and future tools without importing any of them.

See [What belongs where](ownership.md) before adding domain-specific behavior to the shared package.
