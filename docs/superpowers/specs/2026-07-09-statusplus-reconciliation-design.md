# Statusplus 1.7.1 Reconciliation Design

## Goal

Update this repository's Statusplus plugin to the behavior provided by the
Spark repository's version 1.7.1 without modifying the Spark repository or
discarding adaptations that belong to this repository.

## Scope

The reconciliation covers `plugins/statusplus`. It adopts Spark's newer:

- Per-session, atomic JSON cost accumulator
- `/clear`, `/resume`, restart, and stale-render handling
- Stable opening-session LLM headline
- 50-token headline response budget
- Setup and update migrations for the revised headline configuration

Files that are already functionally identical remain unchanged unless required
for consistent line endings.

## Repository-Specific Adaptations

The reconciled plugin preserves:

- Explicit Windows Bash discovery in the setup skill
- This repository's marketplace and repository references
- Existing author metadata
- Existing `statusplus-setup`, `statusplus-update`, and
  `statusplus-llm-setup` skill names

Spark-specific command references and stale rolling-headline documentation will
not be copied.

## Implementation

Runtime scripts will be reconciled first against behavior-focused regression
tests. The tests will establish the expected cost accumulation, reset/resume,
input validation, and headline anchoring behavior before the implementation is
updated.

The three skill files will then be updated to describe and configure the new
runtime while retaining the local Windows behavior. The README and plugin
metadata will be updated last so the documented version and behavior match the
implementation.

## Error Handling and Compatibility

The cost display must tolerate missing, malformed, and legacy state without
breaking the status line. State updates must remain isolated by session and use
atomic replacement.

The headline generator must ignore wrapper noise, cap oversized messages, use
the opening transcript window, and avoid permanently freezing a fallback-only
headline. Existing provider and credential handling remains unchanged.

Legacy Statusplus state and configuration will be migrated where possible.
Unknown user configuration keys will not be removed.

## Verification

Verification will include:

- Regression tests failing against the current implementation, then passing
  against the reconciled implementation
- Python syntax compilation for all Statusplus Python scripts
- JSON parsing for plugin and hook metadata
- A final directory diff confirming that remaining differences from Spark are
  intentional local adaptations
- Git status confirmation that no files in the Spark repository changed

## Non-Goals

- Modifying or committing changes in the Spark repository
- Redesigning the status line layout
- Adding providers or changing credential storage
- Broad refactoring outside `plugins/statusplus` and its focused tests
