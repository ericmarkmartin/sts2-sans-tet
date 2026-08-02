from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from headless.render_environment import verify_render_environment


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")


class RenderEnvironmentTests(unittest.TestCase):
    def make_runtime(self) -> tuple[tempfile.TemporaryDirectory[str], Path, Path, Path]:
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        game = root / "game"
        episode = root / "episode-0001"
        game_dll = game / "data_sts2_windows_x86_64" / "sts2.dll"
        game_dll.parent.mkdir(parents=True)
        game_dll.write_bytes(b"game")
        game_exe = game / "SlayTheSpire2.exe"
        game_exe.write_bytes(b"exe")
        hashes = {
            "SlayTheSpire2.exe": hashlib.sha256(b"exe").hexdigest(),
            "data_sts2_windows_x86_64/sts2.dll": hashlib.sha256(
                b"game"
            ).hexdigest(),
        }
        lock = root / "lock.json"
        write_json(lock, {"schema_version": 1, "release": "test", "files": hashes})
        write_json(
            episode / "manifest.json",
            {"sha256": {"sts2.dll": hashes["data_sts2_windows_x86_64/sts2.dll"]}},
        )
        return temporary, game, episode, lock

    def test_accepts_exact_runtime_and_episode_hash(self) -> None:
        temporary, game, episode, lock = self.make_runtime()
        self.addCleanup(temporary.cleanup)
        report = verify_render_environment(
            game,
            episode,
            lock_path=lock,
            require_commands=False,
            require_free_port=False,
        )
        self.assertTrue(report["valid"], report["errors"])

    def test_rejects_changed_runtime_file(self) -> None:
        temporary, game, episode, lock = self.make_runtime()
        self.addCleanup(temporary.cleanup)
        (game / "SlayTheSpire2.exe").write_bytes(b"changed")
        report = verify_render_environment(
            game,
            episode,
            lock_path=lock,
            require_commands=False,
            require_free_port=False,
        )
        self.assertFalse(report["valid"])
        self.assertTrue(any("hash mismatch" in error for error in report["errors"]))

    def test_rejects_episode_from_different_game_build(self) -> None:
        temporary, game, episode, lock = self.make_runtime()
        self.addCleanup(temporary.cleanup)
        write_json(episode / "manifest.json", {"sha256": {"sts2.dll": "wrong"}})
        report = verify_render_environment(
            game,
            episode,
            lock_path=lock,
            require_commands=False,
            require_free_port=False,
        )
        self.assertFalse(report["valid"])
        self.assertTrue(any("episode game DLL" in error for error in report["errors"]))


if __name__ == "__main__":
    unittest.main()
