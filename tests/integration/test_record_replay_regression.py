#
# Copyright 2025 CoreWeave
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
"""
Record-replay regression tests for kdumpling integration.

These tests verify that:
1. Recording while running regression commands captures all needed memory
2. Replaying on the recorded vmcore produces the same golden output
3. The recorded vmcore is significantly smaller than the original dump

The test workflow:
1. Start recording on the original crash dump
2. Run all regression commands and verify against golden outputs
3. Stop recording (saves vmcore via kdumpling)
4. Print size comparison between original dump and recorded vmcore
5. Load the recorded vmcore with drgn
6. Run all regression commands again and verify against golden outputs
7. Clean up the recorded vmcore
"""

import os
import tempfile
from importlib import import_module
from pathlib import Path
from typing import Any, Dict, Generator, List, Tuple

import pytest

import drgn

import sdb
from sdb.internal.cli import load_debug_info
from sdb.internal.repl import REPL
from sdb.session import (
    get_trace_manager,
    reset_trace_manager,
    TraceManager,
)
from tests.integration.infra import (
    get_crash_dump_dir_paths,
    get_all_reference_crash_dumps,
    get_vmlinux_path,
    get_modules_dir,
    RefDump,
    TEST_OUTPUT_DIR,
)


def get_file_size_mb(path: str) -> float:
    """Get file size in megabytes."""
    return os.path.getsize(path) / (1024 * 1024)


def format_size(size_mb: float) -> str:
    """Format size in human-readable form."""
    if size_mb >= 1024:
        return f"{size_mb / 1024:.2f} GB"
    return f"{size_mb:.2f} MB"


def get_all_regression_commands() -> Dict[str, List[str]]:
    """
    Get all regression test commands from all test modules.

    Returns a dict mapping module name to list of commands.
    """
    modules = {
        'linux': 'test_linux_generic',
        'zfs': 'test_zfs_generic',
        'spl': 'test_spl_generic',
        'mdb_compat': 'test_mdb_compat_generic',
    }

    commands: Dict[str, List[str]] = {}
    for mod_name, test_module in modules.items():
        try:
            test_mod = import_module(f'tests.integration.{test_module}')
            if hasattr(test_mod, 'CMD_TABLE'):
                commands[mod_name] = test_mod.CMD_TABLE
        except ImportError:
            pass
    return commands


def get_reference_data(dump_name: str, modname: str,
                       cmd: str) -> Tuple[str, int]:
    """
    Get the expected output and exit code for a command.

    Args:
        dump_name: Name of the dump directory
        modname: Module name (linux, zfs, etc.)
        cmd: Command string

    Returns:
        Tuple of (expected_output, expected_exit_code)
    """
    output_path = f"{TEST_OUTPUT_DIR}/{dump_name}/{modname}/{cmd}"
    if not os.path.exists(output_path):
        return ("", -1)  # No golden output for this command/dump
    contents = Path(output_path).read_text(encoding='utf-8').splitlines(True)
    return ("".join(contents[:-2]), int(contents[-1].strip()))


# pylint: disable=too-many-arguments,too-many-positional-arguments
def print_size_comparison(capsys: Any, dump_name: str, original_path: str,
                          recorded_path: str, commands_run: int,
                          trace_mgr: TraceManager) -> None:
    """Print size comparison between original and recorded dumps."""
    original_size = get_file_size_mb(original_path)
    recorded_size = get_file_size_mb(recorded_path)
    compression_ratio = (1 - recorded_size / original_size) * 100
    mem_size_mb = trace_mgr.memory.get_total_size() / (1024 * 1024)

    with capsys.disabled():
        print("\n" + "=" * 70)
        print(f"DUMP SIZE COMPARISON: {dump_name}")
        print("=" * 70)
        print(f"Original dump:    {format_size(original_size)}")
        print(f"Recorded vmcore:  {format_size(recorded_size)}")
        print(f"Compression:      {compression_ratio:.1f}% smaller")
        print(f"Commands run:     {commands_run}")
        print(f"Memory segments:  {trace_mgr.memory.get_segment_count()}")
        print(f"Total memory:     {format_size(mem_size_mb)}")
        print("=" * 70 + "\n")


@pytest.fixture(autouse=True)
def reset_trace_manager_fixture() -> Generator[None, None, None]:
    """Reset the trace manager before and after each test."""
    reset_trace_manager()
    yield
    reset_trace_manager()


class ReplayDump:
    """
    Represents a replayed vmcore for running commands.

    Similar to RefDump but loads from a recorded vmcore file.
    """

    program: drgn.Program
    repl: REPL
    dump_name: str

    def __init__(self, vmcore_path: str, dump_name: str,
                 original_dump_dir: str) -> None:
        self.vmcore_path = vmcore_path
        self.dump_name = dump_name
        self.original_dump_dir = original_dump_dir

    def setup_target(self) -> None:
        """Initialize drgn/SDB context for replay."""
        self.program = drgn.Program()
        self.program.set_core_dump(self.vmcore_path)

        # Load debug info from the original dump's vmlinux and modules
        load_debug_info(self.program, [
            get_vmlinux_path(self.original_dump_dir),
            get_modules_dir(self.original_dump_dir)
        ], True, False)

        self.repl = REPL(self.program,
                         list(sdb.get_registered_commands().keys()))

    def repl_invoke(self, cmd: str) -> int:
        """Invoke a command and return exit code."""
        assert self.program
        assert self.repl
        sdb.target.set_prog(self.program)
        sdb.register_commands()
        return self.repl.eval_cmd(cmd)


def run_recording_phase(
    rdump: RefDump, capsys: Any, all_commands: Dict[str, List[str]]
) -> Tuple[Dict[str, Dict[str, Tuple[int, str]]], int]:
    """
    Phase 1: Record while running all regression commands.

    Returns tuple of (record_results dict, commands_run count).
    """
    record_results: Dict[str, Dict[str, Tuple[int, str]]] = {}
    commands_run = 0

    for mod_name, commands in all_commands.items():
        record_results[mod_name] = {}
        for cmd in commands:
            ref_output, ref_code = get_reference_data(rdump.dump_name, mod_name,
                                                      cmd)
            if ref_code == -1:
                continue

            exit_code = rdump.repl_invoke(cmd)
            captured = capsys.readouterr()
            record_results[mod_name][cmd] = (exit_code, captured.out)

            assert exit_code == ref_code, \
                f"[RECORD] {mod_name}/{cmd}: " \
                f"exit code {exit_code} != expected {ref_code}"
            assert captured.out == ref_output, \
                f"[RECORD] {mod_name}/{cmd}: output mismatch"
            commands_run += 1

    return record_results, commands_run


def run_replay_phase(
        replay: ReplayDump, capsys: Any, all_commands: Dict[str, List[str]],
        record_results: Dict[str, Dict[str, Tuple[int, str]]]) -> List[str]:
    """
    Phase 3: Replay all commands on recorded vmcore.

    Returns list of failure messages.
    """
    replay_failures: List[str] = []

    for mod_name, commands in all_commands.items():
        for cmd in commands:
            if mod_name not in record_results:
                continue
            if cmd not in record_results[mod_name]:
                continue

            ref_output, ref_code = get_reference_data(replay.dump_name,
                                                      mod_name, cmd)

            try:
                exit_code = replay.repl_invoke(cmd)
                captured = capsys.readouterr()

                if exit_code != ref_code:
                    replay_failures.append(f"[REPLAY] {mod_name}/{cmd}: "
                                           f"exit code {exit_code} != "
                                           f"expected {ref_code}")
                elif captured.out != ref_output:
                    replay_failures.append(
                        f"[REPLAY] {mod_name}/{cmd}: output mismatch")
            except drgn.FaultError as e:
                replay_failures.append(
                    f"[REPLAY] {mod_name}/{cmd}: FaultError - {e}")
            except Exception as e:  # pylint: disable=broad-exception-caught
                replay_failures.append(
                    f"[REPLAY] {mod_name}/{cmd}: {type(e).__name__} - {e}")

    return replay_failures


@pytest.mark.skipif(
    len(get_crash_dump_dir_paths()) == 0,
    reason="couldn't find any crash/core dumps to run tests against")
class TestRecordReplayRegression:
    """
    End-to-end record-replay regression tests.

    These tests record all regression commands, then replay and verify
    that the recorded vmcore produces identical output.
    """

    @pytest.mark.parametrize('rdump', get_all_reference_crash_dumps())
    def test_record_replay_all_commands(self, rdump: RefDump,
                                        capsys: Any) -> None:
        """
        Test recording and replaying all regression commands.

        This test:
        1. Runs all regression commands while recording
        2. Saves the recorded vmcore
        3. Compares dump sizes
        4. Replays all commands on the recorded vmcore
        5. Verifies output matches golden reference
        """
        sdb.target.set_prog(rdump.program)
        sdb.register_commands()
        all_commands = get_all_regression_commands()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, f"recorded_{rdump.dump_name}")

            # Phase 1: Record
            trace_mgr = get_trace_manager()
            trace_mgr.start_recording(rdump.program, output_path)
            record_results, commands_run = run_recording_phase(
                rdump, capsys, all_commands)
            saved_path = trace_mgr.stop_recording(rdump.program)
            assert os.path.exists(saved_path)

            # Phase 2: Print size comparison
            print_size_comparison(capsys, rdump.dump_name, rdump.dump_path,
                                  saved_path, commands_run, trace_mgr)

            # Phase 3: Replay
            reset_trace_manager()
            replay = ReplayDump(saved_path, rdump.dump_name,
                                rdump.dump_dir_path)
            replay.setup_target()
            get_trace_manager().is_replay = True

            replay_failures = run_replay_phase(replay, capsys, all_commands,
                                               record_results)

            if replay_failures:
                with capsys.disabled():
                    print("\nREPLAY FAILURES:")
                    for failure in replay_failures:
                        print(f"  {failure}")
                pytest.fail(f"Replay failed for {len(replay_failures)} "
                            f"commands. See output above for details.")

    @pytest.mark.parametrize('rdump', get_all_reference_crash_dumps())
    def test_recorded_vmcore_is_smaller(self, rdump: RefDump,
                                        capsys: Any) -> None:
        """
        Verify that the recorded vmcore is smaller than the original dump.

        This is a sanity check to ensure kdumpling is producing efficient
        vmcores that only contain accessed memory.
        """
        sdb.target.set_prog(rdump.program)
        sdb.register_commands()
        all_commands = get_all_regression_commands()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, f"size_test_{rdump.dump_name}")

            trace_mgr = get_trace_manager()
            trace_mgr.start_recording(rdump.program, output_path)

            for mod_name, commands in all_commands.items():
                for cmd in commands[:5]:
                    _, ref_code = get_reference_data(rdump.dump_name, mod_name,
                                                     cmd)
                    if ref_code == -1:
                        continue
                    rdump.repl_invoke(cmd)
                    _ = capsys.readouterr()

            saved_path = trace_mgr.stop_recording(rdump.program)

            original_size = get_file_size_mb(rdump.dump_path)
            recorded_size = get_file_size_mb(saved_path)

            assert recorded_size < original_size, \
                f"Recorded vmcore ({format_size(recorded_size)}) is not " \
                f"smaller than original ({format_size(original_size)})"

            reduction = (1 - recorded_size / original_size) * 100
            with capsys.disabled():
                print(f"\n{rdump.dump_name}: "
                      f"{format_size(original_size)} -> "
                      f"{format_size(recorded_size)} "
                      f"({reduction:.1f}% reduction)")
