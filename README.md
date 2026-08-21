# groundskeeping

`groundskeeping` is a reusable Textual shell for operator tools that inspect, configure, and care for a working environment. It provides page and workbench contracts, safe actions and in-process jobs, setup wizards, oa-configurator inspection and write-flow mechanics, and normalized telemetry primitives.

Consuming applications own their production pages, domain services, safety policy, persistence, and environment-specific help. Groundskeeping owns the consistent interaction around them.

![Groundskeeping demo layout](docs/static/images/demo-layout-example.png)

## Start here

| You want to… | Read… |
|---|---|
| Use an application built with Groundskeeping | [Using a Groundskeeping app](https://australiancancerdatanetwork.github.io/groundskeeping/operator-guide/) |
| Integrate Groundskeeping into an application | [Developer quickstart](https://australiancancerdatanetwork.github.io/groundskeeping/quickstart/) |
| Add configuration inspection or a write flow | [Configuration guide](https://australiancancerdatanetwork.github.io/groundskeeping/configuration/) |
| Understand package boundaries | [What belongs where](https://australiancancerdatanetwork.github.io/groundskeeping/ownership/) |
| Browse public contracts | [API reference](https://australiancancerdatanetwork.github.io/groundskeeping/api/app/) |

## Install

Groundskeeping requires Python 3.12 or newer.

```bash
uv add groundskeeping
```

Run the self-contained demo:

```bash
uv run groundskeeping
```

The self-contained Setup page demonstrates a database-style results table with highlighted-row detail, while Configuration uses a deterministic fake provider so you can try branching, review, and apply behavior without writing a file.

## Minimal composition

A Groundskeeping application starts with an `OperatorAppSpec`. The application wires its own services into its own page factories, then gives the resulting pages to the shell.

```python
from groundskeeping.app import OperatorApp, OperatorAppSpec
from groundskeeping.contracts import PageRegistration, PageRoute

setup_route = PageRoute(
    key="setup",
    label="Setup",
    purpose="Check whether this environment is ready.",
)

spec = OperatorAppSpec(
    app_id="my-tool",
    title="My Tool",
    subtitle="environment setup",
    pages=(
        PageRegistration(
            route=setup_route,
            factory=lambda context: SetupPage(setup_service),
        ),
    ),
)

OperatorApp(spec).run()
```

`SetupPage` and `setup_service` stay in the consuming application. Groundskeeping supplies the frame around them.

## Development

```bash
uv sync --all-extras --dev
uv run pytest -q
uv run ruff check .
uv run ty check src/
```

The full documentation is at [AustralianCancerDataNetwork.github.io/groundskeeping](https://australiancancerdatanetwork.github.io/groundskeeping/).
