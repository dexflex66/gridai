"""
Band collaboration interface — the seam between agents and the collaboration layer.

Defines the ONLY operations agents are allowed to use. When the real Band SDK
arrives, a new implementation of BandInterface replaces MockBand here.
Agents never import MockBand directly; they receive a BandInterface at construction.

Operations modelled:
  register(agent_id, capabilities)   — announce this agent to the collaboration layer
  discover(agent_id)                  — look up a registered agent by id
  send(sender, recipient, msg_type, payload)  — deliver structured context to one agent
  broadcast(sender, msg_type, payload)        — share state with all registered agents
  handoff(sender, recipient, task_type, payload)  — delegate a task with structured payload
  subscribe(agent_id, handler)        — register a callback for incoming messages/handoffs
  drain(agent_id)                     — pull all pending messages for an agent (synchronous polling)
  audit_log()                         — return the full append-only audit log (list of dicts)
"""

from abc import ABC, abstractmethod
from typing import Any, Callable


class BandInterface(ABC):
    """Abstract collaboration layer. Agents depend only on this class."""

    @abstractmethod
    def register(self, agent_id: str, capabilities: list[str]) -> None:
        """Register an agent so others can discover and address it."""

    @abstractmethod
    def discover(self, agent_id: str) -> dict | None:
        """Return registration record for agent_id, or None if not registered."""

    @abstractmethod
    def send(
        self,
        sender: str,
        recipient: str,
        msg_type: str,
        payload: dict,
    ) -> None:
        """Send a structured-context message from sender to recipient."""

    @abstractmethod
    def broadcast(self, sender: str, msg_type: str, payload: dict) -> None:
        """Broadcast shared state to all registered agents."""

    @abstractmethod
    def handoff(
        self,
        sender: str,
        recipient: str,
        task_type: str,
        payload: dict,
    ) -> None:
        """Delegate a task with structured payload to recipient."""

    @abstractmethod
    def subscribe(self, agent_id: str, handler: Callable[[dict], None]) -> None:
        """
        Register handler to be called when agent_id receives a message or handoff.
        handler receives the full message dict (including sender, type, payload).
        """

    @abstractmethod
    def drain(self, agent_id: str) -> list[dict]:
        """Return and clear all pending messages for agent_id."""

    @abstractmethod
    def audit_log(self) -> list[dict]:
        """Return a copy of the full append-only audit log."""
