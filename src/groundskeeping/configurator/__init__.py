"""Safe configuration inspection and provider-neutral write workflows.

This namespace also carries the two test-time surfaces a provider author needs:
:func:`assert_mutation_service_conformance` with its hooks, and the reference fake
providers. Both import only contracts, so importing them costs a runtime host nothing.
"""

from groundskeeping.configurator.adapter import OAConfiguratorAdapter
from groundskeeping.configurator.conformance import (
    MutationConformanceError,
    MutationConformanceHooks,
    MutationServiceFactory,
    assert_mutation_service_conformance,
)
from groundskeeping.configurator.controller import (
    ConfigBranchCondition,
    ConfigWizardController,
    ConfigWorkflowSpec,
    ConfigWorkflowStep,
    ConfigWorkflowStepKind,
)
from groundskeeping.configurator.models import (
    ConfigReferenceStatus,
    ConfigReferenceView,
    ConfigSectionView,
    ConfigTarget,
    ConfigTargetKind,
    ConfiguratorSnapshot,
    RedactedValue,
)
from groundskeeping.configurator.mutation import (
    ConfigApplyIntent,
    ConfigApplyResult,
    ConfigApplyStatus,
    ConfigDiff,
    ConfigDiffEntry,
    ConfigDraft,
    ConfigMutationService,
    ConfigPlan,
    ConfigStepResult,
    EffectRef,
    MutationCapabilities,
    MutationOperation,
    MutationOperationUnsupported,
    UnavailableMutationService,
    build_config_diff,
    resolve_operation,
)
from groundskeeping.configurator.providers import (
    ConfigSchemaAdapter,
    FakeConfigMutationService,
    FakeDialectConfigMutationService,
    FakeMutationEvent,
    FakeMutationScenario,
    SchemaConfigMutationService,
    fake_database_workflow,
    fake_dialect_database_workflow,
)
