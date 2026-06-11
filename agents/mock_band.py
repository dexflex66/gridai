"""
MockBand — in-process implementation of BandInterface for development and testing.

Passes structured messages synchronously. Appends every send/broadcast/handoff
to an append-only audit log with:
  step        monotonically increasing counter (int)
  timestamp   ISO datetime string
  sender      agent_id string
  recipient   agent_id string or "ALL" for broadcasts
  message_type  e.g. "risk_window_handoff", "dispatch_plan_handoff", ...
  payload     the structured dict the sender passed

When real Band arrives, this file is replaced. Agents never import this module
directly — they receive a BandInterface instance at construction time.
"""

import copy
import datetime
from typing import Callable

from agents.band_interface import BandInterface


class MockBand(BandInterface):
    """In-process message bus with full audit logging."""

    def __init__(self) -> None:
        self._registry: dict[str, dict] = {}            # agent_id -> capabilities dict
        self._queues: dict[str, list[dict]] = {}        # agent_id -> pending messages
        self._subscribers: dict[str, Callable] = {}     # agent_id -> handler callable
        self._log: list[dict] = []                      # append-only audit trail
        self._step_counter: int = 0                     # monotonic logical step

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _next_step(self) -> int:
        self._step_counter += 1
        return self._step_counter

    def _now_iso(self) -> str:
        return datetime.datetime.now(datetime.timezone.utc).isoformat()

    def _append_log(self, entry: dict) -> None:
        self._log.append(entry)

    def _deliver(self, recipient: str, message: dict) -> None:
        """Push a message into recipient's queue and fire subscriber if set."""
        if recipient not in self._queues:
            self._queues[recipient] = []
        self._queues[recipient].append(copy.deepcopy(message))

        handler = self._subscribers.get(recipient)
        if handler is not None:
            handler(copy.deepcopy(message))

    # ------------------------------------------------------------------
    # BandInterface implementation
    # ------------------------------------------------------------------

    def register(self, agent_id: str, capabilities: list[str]) -> None:
        self._registry[agent_id] = {"agent_id": agent_id, "capabilities": capabilities}
        self._queues.setdefault(agent_id, [])
        entry = {
            "step": self._next_step(),
            "timestamp": self._now_iso(),
            "sender": agent_id,
            "recipient": "BAND",
            "message_type": "register",
            "payload": {"agent_id": agent_id, "capabilities": capabilities},
        }
        self._append_log(entry)

    def discover(self, agent_id: str) -> dict | None:
        return copy.deepcopy(self._registry.get(agent_id))

    def send(
        self,
        sender: str,
        recipient: str,
        msg_type: str,
        payload: dict,
    ) -> None:
        step = self._next_step()
        ts = self._now_iso()
        message = {
            "step": step,
            "timestamp": ts,
            "sender": sender,
            "recipient": recipient,
            "message_type": msg_type,
            "payload": copy.deepcopy(payload),
        }
        self._append_log(message)
        self._deliver(recipient, message)

    def broadcast(self, sender: str, msg_type: str, payload: dict) -> None:
        step = self._next_step()
        ts = self._now_iso()
        entry = {
            "step": step,
            "timestamp": ts,
            "sender": sender,
            "recipient": "ALL",
            "message_type": msg_type,
            "payload": copy.deepcopy(payload),
        }
        self._append_log(entry)
        for agent_id in list(self._registry.keys()):
            if agent_id == sender:
                continue
            msg_copy = dict(entry)
            msg_copy["recipient"] = agent_id
            self._deliver(agent_id, msg_copy)

    def handoff(
        self,
        sender: str,
        recipient: str,
        task_type: str,
        payload: dict,
    ) -> None:
        step = self._next_step()
        ts = self._now_iso()
        message = {
            "step": step,
            "timestamp": ts,
            "sender": sender,
            "recipient": recipient,
            "message_type": f"handoff:{task_type}",
            "payload": copy.deepcopy(payload),
        }
        self._append_log(message)
        self._deliver(recipient, message)

    def subscribe(self, agent_id: str, handler: Callable[[dict], None]) -> None:
        self._subscribers[agent_id] = handler

    def drain(self, agent_id: str) -> list[dict]:
        msgs = list(self._queues.get(agent_id, []))
        self._queues[agent_id] = []
        return msgs

    def audit_log(self) -> list[dict]:
        return copy.deepcopy(self._log)
