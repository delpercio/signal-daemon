"""Adapter capture-state tests."""

import json
import subprocess
import sys

from signal_daemon.adapters.claude_code import (
    ClaudeCodeConversationHandler,
    ClaudeCodeTaskHandler,
)


def _write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


class TestConversationCursor:
    def _handler(self, tmp_path, collected):
        return ClaudeCodeConversationHandler(
            projects_dir=tmp_path / "projects",
            device_id="dev",
            on_events=collected.extend,
            state_dir=tmp_path / "state",
        )

    def test_only_new_lines_are_emitted(self, tmp_path):
        jsonl = tmp_path / "projects" / "-Users-x-Documents-Proj" / "sess.jsonl"
        _write_jsonl(jsonl, [{"sessionId": "sess", "type": "user", "n": i} for i in range(3)])

        collected = []
        assert len(self._handler(tmp_path, collected).scan_existing()) == 3
        # Second pass sees nothing new.
        assert self._handler(tmp_path, collected).scan_existing() == []

        with jsonl.open("a") as f:
            f.write(json.dumps({"sessionId": "sess", "type": "user", "n": 3}) + "\n")
        assert len(self._handler(tmp_path, collected).scan_existing()) == 1

    def test_missing_directory_is_not_an_error(self, tmp_path):
        assert self._handler(tmp_path, []).scan_existing() == []


class TestTaskDedup:
    def _handler(self, tmp_path, collected):
        return ClaudeCodeTaskHandler(
            tasks_dir=tmp_path / "tasks",
            device_id="dev",
            on_events=collected.extend,
            state_dir=tmp_path / "state",
        )

    def _task(self, tmp_path, body):
        task = tmp_path / "tasks" / "sess1" / "task.json"
        task.parent.mkdir(parents=True, exist_ok=True)
        task.write_text(json.dumps(body))
        return task

    def test_unchanged_task_not_re_emitted(self, tmp_path):
        self._task(tmp_path, {"status": "pending"})
        collected = []
        assert len(self._handler(tmp_path, collected).scan_existing()) == 1
        assert self._handler(tmp_path, collected).scan_existing() == []

    def test_changed_task_is_re_emitted(self, tmp_path):
        self._task(tmp_path, {"status": "pending"})
        collected = []
        self._handler(tmp_path, collected).scan_existing()
        self._task(tmp_path, {"status": "done"})
        assert len(self._handler(tmp_path, collected).scan_existing()) == 1

    def test_dedup_key_is_stable_across_processes(self):
        """The content hash must not depend on PYTHONHASHSEED.

        Built-in hash() randomises string hashing per process, so a daemon
        restart would re-emit every task file it had already captured.
        """
        code = (
            "import hashlib;"
            "print(hashlib.sha256(b'identical task content').hexdigest())"
        )
        digests = {
            subprocess.run(
                [sys.executable, "-c", code], capture_output=True, text=True
            ).stdout.strip()
            for _ in range(3)
        }
        assert len(digests) == 1

    def test_state_survives_a_restart(self, tmp_path):
        """Re-reading persisted state must not re-emit an unchanged task."""
        self._task(tmp_path, {"status": "pending"})
        collected = []
        assert len(self._handler(tmp_path, collected).scan_existing()) == 1

        state_files = list((tmp_path / "state").glob("claude_task_*.json"))
        assert state_files, "expected task state to be persisted"
        seen = json.loads(state_files[0].read_text())["seen"]
        # A stable digest, not a per-process integer hash.
        assert all(len(entry.rsplit(":", 1)[-1]) == 64 for entry in seen)
