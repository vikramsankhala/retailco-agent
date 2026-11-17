# Peer design and code review checklist

Reviewer: ______  Author: ______  Date: ______

Give each item: yes / no / not applicable, with a line of evidence (file, test or trace).

## The problem
- [ ] The problem brief names the user, the measure of success and the stop conditions.
- [ ] Each requirement maps to a layer, a module and a test or golden case.

## Safety and control
- [ ] Identity comes from the verified session, never from model output.
- [ ] Every write tool has an idempotency key and a limit enforced in code.
- [ ] Actions above a limit wait for a person, and that wait survives a restart.
- [ ] Retrieved text and tool results are treated as data (scanned, marked, never obeyed).
- [ ] There is a kill switch and someone knows how to use it.

## Quality
- [ ] Golden set covers each intent, each route and the known failure modes.
- [ ] Red-team suite covers each OWASP LLM item that applies.
- [ ] A/B comparison shows no regression against the current version.

## Operations
- [ ] Service levels have targets, owners and alerts.
- [ ] Traces contain no personal data.
- [ ] Rollback takes one command and has been rehearsed.

## Code
- [ ] Tests run offline in under a minute.
- [ ] Thresholds live in one configuration file.
- [ ] Names, comments and errors would make sense to the next engineer.

Top three issues, most important first:
1.
2.
3.
