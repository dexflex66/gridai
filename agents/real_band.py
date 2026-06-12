"""
RealBand — BandInterface implementation backed by the real Band platform
(thenvoi REST API, package `band-sdk` / client `thenvoi_rest`).

Design: Band-as-transport-bus. Our four agents are deterministic sim-driven
orchestrators, not LLM agents, so we use Band purely as the collaboration
transport + native audit trail:

  register  -> resolve the agent's Band identity; ensure it is a participant in
               one shared coordination room (the first registrant creates it and
               owns it, then adds the others)
  send/handoff -> the SENDER's authenticated client posts a chat message to the
               room, @mentioning the RECIPIENT, with the structured payload
               carried as a JSON envelope in the message content
  broadcast -> a room message @mentioning every other agent
  drain     -> the agent's client pulls its own inbox (get_agent_next_message),
               parses the JSON envelope, and marks each message processed
  audit_log -> a local append-only mirror in the exact MockBand shape (so the
               verification suite behaves identically). The Band room messages
               are ALSO the native trail; fetch them with native_trail().

Determinism / parity: all headline numbers come from the LOCAL sim run inside the
Coordinator. Band only carries the JSON envelopes, so decision records are
identical to the mock run field-by-field (Band is a pipe, not a computer).

The four agents are UNCHANGED and depend only on BandInterface. Selection between
MockBand and RealBand happens in band_interface.get_band() via USE_REAL_BAND.
"""

import copy
import datetime
import json
import os
import re
import time
from typing import Callable

from agents.band_interface import BandInterface

DEFAULT_BASE_URL = "https://app.band.ai"

# Our internal agent_id -> environment variable holding that agent's Band API key.
AGENT_ENV_KEYS = {
    "forecaster":  "BAND_FORECASTER_API_KEY",
    "coordinator": "BAND_COORDINATOR_API_KEY",
    "compliance":  "BAND_COMPLIANCE_API_KEY",
    "operator":    "BAND_OPERATOR_API_KEY",
}

# Strip the platform-injected "@[[uuid]] " mention prefix before parsing JSON.
_MENTION_PREFIX = re.compile(r"^\s*(?:@\[\[[^\]]+\]\]\s*)+")

# How long drain() waits for an expected message to appear (eventual consistency).
_DRAIN_POLL_SECONDS = float(os.getenv("BAND_DRAIN_POLL_SECONDS", "6"))
_DRAIN_POLL_INTERVAL = 0.5


class RealBand(BandInterface):
    """BandInterface backed by the live Band platform over REST."""

    def __init__(self, base_url: str | None = None, room_id: str | None = None) -> None:
        # Imported lazily so the rest of the project never hard-depends on the SDK.
        from thenvoi_rest import (
            RestClient,
            ChatRoomRequest,
            ChatMessageRequest,
            ChatMessageRequestMentionsItem,
            ParticipantRequest,
        )
        self._RestClient = RestClient
        self._ChatRoomRequest = ChatRoomRequest
        self._ChatMessageRequest = ChatMessageRequest
        self._MentionItem = ChatMessageRequestMentionsItem
        self._ParticipantRequest = ParticipantRequest

        self._base_url = base_url or os.getenv("THENVOI_REST_URL") or DEFAULT_BASE_URL

        self._clients: dict[str, object] = {}     # agent_id -> RestClient
        self._identity: dict[str, dict] = {}       # agent_id -> {id, handle, name}
        self._registry: dict[str, dict] = {}       # agent_id -> {agent_id, capabilities}
        self._subscribers: dict[str, Callable] = {}
        self._log: list[dict] = []                 # local mirror in MockBand shape
        self._step_counter = 0

        self.room_id: str | None = room_id
        self._owner: str | None = None             # agent_id that created/owns the room

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

    def _client(self, agent_id: str):
        if agent_id not in self._clients:
            env = AGENT_ENV_KEYS.get(agent_id)
            if env is None:
                raise KeyError(f"No Band API key mapping for agent_id={agent_id!r}")
            key = os.environ.get(env)
            if not key:
                raise RuntimeError(f"Environment variable {env} is not set (need it for RealBand)")
            self._clients[agent_id] = self._RestClient(
                api_key=key, base_url=self._base_url, timeout=30
            )
        return self._clients[agent_id]

    def _resolve_identity(self, agent_id: str) -> dict:
        if agent_id not in self._identity:
            me = self._client(agent_id).agent_api_identity.get_agent_me().data
            self._identity[agent_id] = {"id": me.id, "handle": me.handle, "name": me.name}
        return self._identity[agent_id]

    def _ensure_room(self, creator_agent_id: str) -> str:
        if self.room_id is None:
            client = self._client(creator_agent_id)
            room = client.agent_api_chats.create_agent_chat(chat=self._ChatRoomRequest())
            self.room_id = room.data.id
            self._owner = creator_agent_id
        return self.room_id

    def _add_participant(self, agent_id: str) -> None:
        """Owner adds agent_id to the room as a member (idempotent-ish)."""
        if self._owner is None or agent_id == self._owner:
            return
        owner_client = self._client(self._owner)
        ident = self._resolve_identity(agent_id)
        try:
            owner_client.agent_api_participants.add_agent_chat_participant(
                self.room_id,
                participant=self._ParticipantRequest(participant_id=ident["id"], role="member"),
            )
        except Exception:
            # already a participant, or a benign conflict — safe to ignore
            pass

    def _post(self, sender: str, recipient: str, message_type: str, payload: dict) -> dict:
        """Mirror to the local log AND post to the Band room, @mentioning recipient."""
        step = self._next_step()
        ts = self._now_iso()
        entry = {
            "step": step,
            "timestamp": ts,
            "sender": sender,
            "recipient": recipient,
            "message_type": message_type,
            "payload": copy.deepcopy(payload),
        }
        self._append_log(entry)

        envelope = {
            "sender": sender,
            "recipient": recipient,
            "message_type": message_type,
            "payload": payload,
            "step": step,
            "timestamp": ts,
        }
        recipients = (
            [a for a in self._registry if a != sender]
            if recipient == "ALL"
            else [recipient]
        )
        mentions = []
        for r in recipients:
            ident = self._resolve_identity(r)
            mentions.append(self._MentionItem(id=ident["id"], handle=ident["handle"], name=ident["name"]))
        self._client(sender).agent_api_messages.create_agent_chat_message(
            self.room_id,
            message=self._ChatMessageRequest(content=json.dumps(envelope), mentions=mentions),
        )
        return entry

    @staticmethod
    def _parse_envelope(content: str) -> dict | None:
        stripped = _MENTION_PREFIX.sub("", content or "")
        brace = stripped.find("{")
        if brace == -1:
            return None
        try:
            return json.loads(stripped[brace:])
        except json.JSONDecodeError:
            return None

    # ------------------------------------------------------------------
    # BandInterface implementation
    # ------------------------------------------------------------------

    def register(self, agent_id: str, capabilities: list[str]) -> None:
        self._resolve_identity(agent_id)          # authenticates the key
        self._registry[agent_id] = {"agent_id": agent_id, "capabilities": capabilities}
        self._ensure_room(agent_id)               # first registrant creates+owns the room
        self._add_participant(agent_id)           # owner adds everyone else
        self._append_log({
            "step": self._next_step(),
            "timestamp": self._now_iso(),
            "sender": agent_id,
            "recipient": "BAND",
            "message_type": "register",
            "payload": {"agent_id": agent_id, "capabilities": capabilities},
        })

    def discover(self, agent_id: str) -> dict | None:
        rec = self._registry.get(agent_id)
        if rec is None:
            return None
        out = copy.deepcopy(rec)
        out["band_identity"] = copy.deepcopy(self._identity.get(agent_id))
        return out

    def send(self, sender: str, recipient: str, msg_type: str, payload: dict) -> None:
        self._post(sender, recipient, msg_type, payload)

    def broadcast(self, sender: str, msg_type: str, payload: dict) -> None:
        self._post(sender, "ALL", msg_type, payload)

    def handoff(self, sender: str, recipient: str, task_type: str, payload: dict) -> None:
        self._post(sender, recipient, f"handoff:{task_type}", payload)

    def subscribe(self, agent_id: str, handler: Callable[[dict], None]) -> None:
        self._subscribers[agent_id] = handler

    def drain(self, agent_id: str) -> list[dict]:
        """Pull this agent's inbox from Band, parse envelopes, mark each consumed.

        Platform semantics (verified live):
          - get_agent_next_message returns this agent's next addressed message;
            an EMPTY inbox returns HTTP 204, which the SDK raises as ApiError.
          - a message must be transitioned processing -> processed to be consumed;
            marking a pending message processed directly is a 422.
        Polls up to _DRAIN_POLL_SECONDS to absorb delivery latency, then returns.
        """
        from thenvoi_rest.core.api_error import ApiError

        client = self._client(agent_id)
        room = self.room_id
        if room is None:
            return []
        msgs: list[dict] = []
        seen: set[str] = set()                 # guard against any re-delivery loop
        deadline = time.monotonic() + _DRAIN_POLL_SECONDS
        while True:
            data = None
            try:
                data = getattr(client.agent_api_messages.get_agent_next_message(room), "data", None)
            except ApiError:
                data = None                    # 204 (empty) or transient — treat as empty
            except Exception:
                data = None

            if data is not None and getattr(data, "id", None) not in seen:
                mid = data.id
                seen.add(mid)
                # claim the message (pending -> processing) so the queue advances
                try:
                    client.agent_api_messages.mark_agent_message_processing(room, mid)
                except Exception:
                    pass
                envelope = self._parse_envelope(getattr(data, "content", "") or "")
                if envelope is not None:
                    message = {
                        "step": envelope.get("step"),
                        "timestamp": envelope.get("timestamp"),
                        "sender": envelope.get("sender"),
                        "recipient": envelope.get("recipient"),
                        "message_type": envelope.get("message_type"),
                        "payload": envelope.get("payload"),
                    }
                    msgs.append(message)
                    handler = self._subscribers.get(agent_id)
                    if handler is not None:
                        handler(copy.deepcopy(message))
                # finish consuming (processing -> processed)
                try:
                    client.agent_api_messages.mark_agent_message_processed(room, mid)
                except Exception:
                    pass
                continue                       # drain everything currently queued

            if msgs or time.monotonic() >= deadline:
                break                          # got something, or waited long enough
            time.sleep(_DRAIN_POLL_INTERVAL)   # nothing yet — wait for delivery
        return msgs

    def audit_log(self) -> list[dict]:
        return copy.deepcopy(self._log)

    # ------------------------------------------------------------------
    # RealBand-only helpers (NOT part of BandInterface; agents never call these)
    # ------------------------------------------------------------------

    def native_trail(self, viewer_agent_id: str = "coordinator") -> list[dict]:
        """Fetch the Band-native message trail for the room (the real collaboration
        record), as seen by one participant. For reporting / inspection only."""
        if self.room_id is None:
            return []
        client = self._client(viewer_agent_id)
        resp = client.agent_api_messages.list_agent_messages(self.room_id, status="all")
        out = []
        for m in getattr(resp, "data", []) or []:
            d = m.model_dump() if hasattr(m, "model_dump") else dict(m)
            env = self._parse_envelope(d.get("content", "") or "")
            out.append({
                "band_message_id": d.get("id"),
                "sender_id": d.get("sender_id"),
                "sender_name": d.get("sender_name"),
                "inserted_at": str(d.get("inserted_at")),
                "message_type": (env or {}).get("message_type"),
                "recipient": (env or {}).get("recipient"),
            })
        return out
