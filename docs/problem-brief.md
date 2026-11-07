# RetailCo support agent: problem brief

## Problem
RetailCo (UK e-commerce, £180M revenue, 1.2M active customers, 45,000 SKUs) handles 15,000+
support interactions a day across chat, email and phone. First response averages 4.2 hours
(benchmark: 1 hour). CSAT has fallen from 78% to 61% in 18 months. Support costs £3.2M a year,
growing 22% a year. 68% of tickets are tier-1 (order status, refunds, address changes).
Agent attrition is 35%.

## Users
Customers on chat (Phase 1), then email and voice. Support agents who handle escalations and approvals.

## Success criteria
| Measure | Target | How measured | Owner |
|---|---|---|---|
| Containment | > 75% | Requests closed without an escalation row | Head of Support |
| CSAT | > 80% | Post-interaction survey | Head of CX |
| Tier-1 response time | < 30 s | Trace duration, p95 | Engineering lead |
| Cost per interaction | < £0.15 (human: £0.72) | Token usage per trace x price list | Finance partner |
| Critical safety incidents | 0 | Incident log; guard denials reviewed weekly | Risk owner |

Guard-rail metrics: repeat contacts within 48 hours; refunds reversed; complaints about the assistant.
Baseline: measured on the human process for the four weeks before the pilot, same definitions.

## Scope
In (Phase 1): tracking, late-delivery refunds (automatic up to £200, human approval above),
full-order returns, address changes, policy questions.
Out (Phase 1): partial returns, complaints, fraud queries, multi-item order issues (Phase 2).

## Policy
Late Delivery Guarantee: 7+ days late = full refund; 3-6 days late = £5 goodwill credit.

## Top risks
| Risk | Mitigation |
|---|---|
| Prompt injection triggers refunds | Intake screen + PreToolUse guard + in-tool £200 check |
| Cross-account data exposure | Ownership checked in every tool from the verified session |
| Duplicate refunds on retry | Idempotency key refund:<order_id> |
| Carrier API outages | Cache fallback with timestamp; circuit breaker |
| Invented amounts or references in replies | Mechanical grounding check before sending |

## Open questions
- Who staffs the approval queue out of hours?
- Which survey question defines CSAT for chat?
