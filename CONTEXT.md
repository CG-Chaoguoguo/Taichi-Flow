# Taichi-Flow Workbench

Taichi-Flow organizes immutable scientific inputs, parameter scenarios, queued solver runs, and reproducible result exports around a local project workspace.

## Language

**Project**:
A local workspace that owns shared input revisions, scenarios, runs, results, and exports.
_Avoid_: Case, workspace session

**Input Revision**:
An immutable, validated manifest of content-addressed project input files.
_Avoid_: Current upload, mutable input set

**Scenario**:
A named parameter patch pinned to exactly one input revision.
_Avoid_: Simulation, case

**Simulation Run**:
One execution of a scenario that records a frozen effective configuration and terminal outcome.
_Avoid_: Scenario, job

**Queue Item**:
A persisted request to execute a scenario, with ordering and lifecycle state.
_Avoid_: Simulation, task

**Result Family**:
A typed collection of files produced by one simulation run.
_Avoid_: Export

**Export Job**:
An asynchronous package request that selects verified result files and parameter snapshots.
_Avoid_: Result

## Relationships

- A **Project** owns zero or more **Input Revisions** and **Scenarios**.
- A **Scenario** references exactly one **Input Revision**.
- A **Queue Item** references exactly one **Scenario** and may create one **Simulation Run**.
- A **Simulation Run** owns zero or more **Result Families**.
- An **Export Job** references one completed **Simulation Run**.

## Example dialogue

> **Dev:** "Can I change the rainfall files on a completed scenario?"
> **Domain expert:** "No. Publish a new Input Revision, then duplicate the Scenario and pin the copy to that revision."

## Flagged ambiguities

- “算例” previously meant both imported text input and an executable configuration; resolved: imported files become an **Input Revision**, while executable parameter variants are **Scenarios**.
- “任务” previously meant both queue entry and solver execution; resolved: these are **Queue Item** and **Simulation Run** respectively.
