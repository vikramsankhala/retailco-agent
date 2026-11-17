# ADR-0002: Keep approvals as a state machine in the database

- Status: accepted
- Date: 2024-11-05 (lab date)
- Deciders: engineering lead, risk (Fiona Okafor), payments (Martin Hale)

## Context
Refunds above £200 need a senior colleague (R3). The decision can come hours after the request,
and the service restarts during deployments. An approval held in memory would be lost; an approval
executed twice would refund twice (R8).

## Options considered
| Option | For | Against |
|---|---|---|
| In-memory queue | Simplest | Lost on restart |
| Workflow engine (Temporal, Step Functions) | Built for long-running work | New platform to run for one workflow |
| State machine in the existing database | Survives restarts, uses tools we have | We own the resume logic |

## Decision
`approvals.ApprovalService`: pending, approved or rejected, then executed or closed, with a
compare-and-set decision, idempotency keys on execution and `resume()` at start-up.

## Consequences
Two reviewers cannot both decide. A crash between decision and refund is finished on restart.
Revisit when more than three workflows need waiting states: then a workflow engine pays for itself.

## Evidence
`tests/test_long_running.py::test_approval_survives_a_restart_and_refunds_exactly_once`.
