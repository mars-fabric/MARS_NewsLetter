"""Cost collector — reads JSON files written by cmbagent's ``display_cost()``.

Single path for cost data to reach our database and (optionally) the WebSocket
clients. Mirrors ``MARS-PaperPulse/backend/execution/cost_collector.py`` so both
products share the same cost-tracking semantics.

The collector is **never allowed to crash the workflow** — every failure is
logged and swallowed.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class CostCollector:
    """Reads cost JSON from ``work_dir/cost/`` and persists to the cmbagent DB."""

    def __init__(self, db_session, session_id: str, run_id: str):
        self.db_session = db_session
        self.session_id = session_id
        self.run_id = run_id
        self._processed_files: set = set()

    def collect_from_callback(
        self,
        cost_data: Dict[str, Any],
        ws_send_func: Optional[Callable] = None,
    ) -> None:
        """Process cost data received via the cmbagent ``on_cost_update`` callback."""
        try:
            json_path = cost_data.get("cost_json_path")
            records = cost_data.get("records", [])

            if json_path and json_path in self._processed_files:
                return

            if json_path:
                self._processed_files.add(json_path)

            if not records and json_path and os.path.exists(json_path):
                try:
                    with open(json_path, "r") as f:
                        records = json.load(f)
                except Exception as exc:
                    logger.error("cost_json_read_failed path=%s error=%s", json_path, exc)
                    return

            self._persist_records(records)
            if ws_send_func:
                self._emit_ws_events(records, ws_send_func)
        except Exception as exc:
            logger.error("cost_collect_failed error=%s", exc)

    def collect_from_work_dir(
        self,
        work_dir: str,
        ws_send_func: Optional[Callable] = None,
    ) -> None:
        """Scan ``work_dir/cost/`` for any unprocessed JSON files."""
        cost_dir = os.path.join(work_dir, "cost")
        if not os.path.isdir(cost_dir):
            return
        for fname in sorted(os.listdir(cost_dir)):
            if not fname.endswith(".json"):
                continue
            json_path = os.path.join(cost_dir, fname)
            if json_path not in self._processed_files:
                self.collect_from_callback(
                    {"cost_json_path": json_path},
                    ws_send_func=ws_send_func,
                )

    def _persist_records(self, records: List[Dict]) -> None:
        if not self.db_session:
            return
        try:
            from cmbagent.database.repository import CostRepository  # type: ignore

            cost_repo = CostRepository(self.db_session, self.session_id)
            for entry in records:
                if entry.get("Agent") == "Total":
                    continue

                cost_str = str(entry.get("Cost ($)", "$0.0"))
                cost_value = float(cost_str.replace("$", ""))
                prompt_tokens = int(float(str(entry.get("Prompt Tokens", 0))))
                completion_tokens = int(float(str(entry.get("Completion Tokens", 0))))

                if cost_value > 0 or prompt_tokens > 0 or completion_tokens > 0:
                    cost_repo.record_cost(
                        run_id=self.run_id,
                        model=entry.get("Model", "unknown"),
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        cost_usd=cost_value,
                        agent_name=entry.get("Agent", "unknown"),
                    )
        except Exception as exc:
            logger.error("cost_persist_failed error=%s", exc)
            try:
                self.db_session.rollback()
            except Exception:
                pass

    def _emit_ws_events(self, records: List[Dict], ws_send_func: Callable) -> None:
        total_cost = 0.0
        for entry in records:
            if entry.get("Agent") == "Total":
                continue
            cost_str = str(entry.get("Cost ($)", "$0.0"))
            cost_value = float(cost_str.replace("$", ""))
            total_cost += cost_value
            ws_send_func(
                "cost_update",
                {
                    "run_id": self.run_id,
                    "agent": entry.get("Agent", "unknown"),
                    "model": entry.get("Model", "unknown"),
                    "tokens": int(float(str(entry.get("Total Tokens", 0)))),
                    "input_tokens": int(float(str(entry.get("Prompt Tokens", 0)))),
                    "output_tokens": int(float(str(entry.get("Completion Tokens", 0)))),
                    "cost_usd": cost_value,
                    "total_cost_usd": total_cost,
                },
            )
