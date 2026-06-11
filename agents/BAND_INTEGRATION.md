# Band Integration Guide

## What changes when real Band arrives

When the real Band SDK is available, **only one file changes**: `agents/mock_band.py` is
replaced by a new implementation of `BandInterface`. The four agents (forecaster, coordinator,
compliance, grid_operator) depend only on `BandInterface` and are untouched.

## Interface → SDK mapping

Each method in `BandInterface` maps to an anticipated Band SDK call:

| BandInterface method | Anticipated Band SDK call | Notes |
|---|---|---|
| `register(agent_id, capabilities)` | `band.agents.register(id=agent_id, metadata={capabilities})` | Called once at agent startup |
| `discover(agent_id)` | `band.agents.get(id=agent_id)` | Returns agent metadata or None |
| `send(sender, recipient, msg_type, payload)` | `band.messages.send(to=recipient, type=msg_type, body=payload)` | Structured context message |
| `broadcast(sender, msg_type, payload)` | `band.messages.broadcast(type=msg_type, body=payload)` | Shared state to all agents |
| `handoff(sender, recipient, task_type, payload)` | `band.tasks.delegate(to=recipient, task=task_type, context=payload)` | Task delegation with full payload |
| `subscribe(agent_id, handler)` | `band.on_message(handler)` or webhook registration | Called at agent startup |
| `drain(agent_id)` | `band.messages.poll()` or push model via subscribe | Synchronous poll → may become event-driven |
| `audit_log()` | `band.audit.list()` or equivalent | Band likely maintains its own audit trail |

## What the agents send and receive

```
Forecaster  --handoff:risk_window-->            Coordinator
Coordinator --handoff:dispatch_plan_and_trajectory-->  Compliance
Compliance  --handoff:compliance_escalation-->  Operator   (breach detected)
Compliance  --send:compliance_approval-->       Operator   (clean plan)
Operator    --broadcast:operator_decision-->    ALL
```

All payloads are plain Python dicts (JSON-serialisable). No numpy arrays cross the Band
boundary — coordinators convert to Python lists before handing off.

## Open questions for Band hacker guide

1. **Auth**: what token/credential does an agent use to register? OAuth, API key, or session?
2. **Message format**: does Band enforce a schema per message_type, or is the payload opaque JSON?
3. **Discovery**: is agent discovery eventual-consistent (cached) or strongly consistent?
4. **Handoff semantics**: does Band guarantee at-least-once delivery? Can a handoff be
   rejected/bounced if recipient is not registered?
5. **Audit trail ownership**: does Band maintain the canonical audit trail, or do agents
   write to it explicitly? If Band owns it, `audit_log()` maps to a Band query.
6. **Subscribe model**: push (webhooks/SSE) or poll? The mock uses synchronous poll
   (`drain`); the real SDK may be async.
7. **Context sharing**: does Band support a shared key-value state store (for broadcast
   state like grid metrics) separate from point-to-point messages?
8. **Message retention**: how long does Band retain unread messages? Relevant if an agent
   is temporarily offline.

## Swap procedure (post-kickoff)

1. Copy `agents/mock_band.py` → `agents/real_band.py`.
2. Implement each method using the real Band SDK client.
3. In `agents/run_agents.py` (and any test fixtures that construct `MockBand`), swap
   `MockBand()` for `RealBand(api_key=..., ...)`.
4. Run `pytest tests/test_agents.py` — all assertions about agent behaviour should pass
   unchanged. Only Band-internal assertions (MockBand-specific properties) will need updating.
5. The audit log in Band's own system replaces `outputs/band_audit_*.json`.
