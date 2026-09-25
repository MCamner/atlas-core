"""v1.5 first write use case: a proposed patch becomes a new branch on approval.

Everything before the approval happens in a throwaway clone; the only write is
one compare-and-swap ref creation under `refs/heads/atlas/`.
"""
from __future__ import annotations

import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from typing import Any

from atlas_core.approval import ApprovalRejected
from atlas_core.cli import main
from atlas_core.eventlog import EventLog
from atlas_core.patch_proposal import (
    Proposal, ProposalRefused, prepare, propose, validate_branch,
)

PASSES = [sys.executable, "-c",
          "import pathlib,sys; sys.exit(0 if 'fixed' in pathlib.Path('README.md').read_text() else 1)"]
FIX = b"""diff --git a/README.md b/README.md
--- a/README.md
+++ b/README.md
@@ -1 +1 @@
-broken
+fixed
"""


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


def refs(root: Path) -> str:
    return git(root, "for-each-ref", "--format=%(refname) %(objectname)")


class Repo(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "repo"
        self.root.mkdir()
        git(self.root, "init", "-q", "-b", "main")
        (self.root / "README.md").write_text("broken\n")
        git(self.root, "add", ".")
        self.commit("one")
        self.base = git(self.root, "rev-parse", "HEAD")
        self.before = refs(self.root)
        self.log = EventLog(run_id="run-1")
        self.shown = ""
        self.clones_before = set(Path(tempfile.gettempdir()).glob("atlas-proposal-*"))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def commit(self, message: str) -> None:
        git(self.root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", message)

    def propose(self, answer: Any = "approve", patch: bytes = FIX,
                branch: str = "atlas/fix-readme", test: list[str] = PASSES) -> dict[str, Any]:
        def ask(text: str) -> str:
            self.shown = text
            if callable(answer):
                return str(answer(text))
            return text.rsplit("operation  : ", 1)[1][:12] if answer == "approve" else answer
        return propose(str(self.root), patch, branch, test,
                       ask=None if answer is None else ask, granted_by="mattias", log=self.log)

    def decisions(self) -> list[str]:
        return [e.payload["decision"] for e in self.log.events() if e.kind == "approval_recorded"]

    def assert_untouched(self) -> None:
        self.assertEqual(refs(self.root), self.before)
        self.assertEqual(git(self.root, "rev-parse", "HEAD"), self.base)
        self.assertEqual(git(self.root, "status", "--porcelain"), "")
        self.assertEqual(git(self.root, "symbolic-ref", "HEAD"), "refs/heads/main")

    def assert_no_clone_left(self) -> None:
        self.assertEqual(set(Path(tempfile.gettempdir()).glob("atlas-proposal-*")),
                         self.clones_before)


class TestApprovedProposal(Repo):
    def test_an_exact_yes_creates_one_branch_and_nothing_else(self) -> None:
        result = self.propose()
        self.assertEqual(result["outcome"], "branch_created")
        branch = git(self.root, "rev-parse", "refs/heads/atlas/fix-readme")
        self.assertEqual(branch, result["commit"])
        self.assertEqual(git(self.root, "rev-parse", f"{branch}^"), self.base)
        self.assertEqual(git(self.root, "show", f"{branch}:README.md"), "fixed")
        # main, HEAD, the worktree and every other ref are as they were.
        self.assertEqual(git(self.root, "rev-parse", "main"), self.base)
        self.assertEqual(git(self.root, "symbolic-ref", "HEAD"), "refs/heads/main")
        self.assertEqual((self.root / "README.md").read_text(), "broken\n")
        self.assertEqual(git(self.root, "status", "--porcelain"), "")
        self.assertEqual(git(self.root, "remote"), "")
        self.assertEqual(self.decisions(), ["requested", "granted", "consumed"])
        self.assertIn("+fixed", self.shown)
        self.assertIn("exit 0", self.shown)
        self.assert_no_clone_left()

    def test_the_approved_operation_names_the_diff_it_shows(self) -> None:
        proposal = prepare(str(self.root), FIX, "atlas/x", PASSES)
        try:
            op = proposal.operation()
            self.assertEqual(op.arguments["diff_sha256"], proposal.diff_sha256)
            self.assertEqual(op.ref, "refs/heads/atlas/x")
            self.assertEqual(op.head, self.base)
        finally:
            from atlas_core.patch_proposal import discard
            discard(proposal)
        self.assert_untouched()


class TestPostAction(Repo):
    def test_a_created_branch_is_verified_from_the_repository(self) -> None:
        result = self.propose()
        post = result["post_action"]
        self.assertTrue(post["verified"])
        self.assertEqual([c["name"] for c in post["checks"] if c["passed"]], [
            "ref_points_at_commit", "parent_is_base", "diff_is_approved",
            "only_this_ref_changed", "head_and_worktree_untouched", "tests_pass_on_branch"])
        self.assertEqual(post["tests"]["exit_code"], 0)
        self.assertFalse(post["rollback"]["attempted"])
        self.assertEqual(post["rollback"]["command"][-3:],
                         ["-d", "refs/heads/atlas/fix-readme", result["commit"]])
        irreversible = [e["what"] for e in post["side_effects"] if not e["reversible"]]
        self.assertEqual(len(irreversible), 2)
        self.assertIn("fetched the proposal's objects", irreversible[0])
        self.assertIn("ran ", irreversible[1])
        self.assertFalse(any(c["skipped"] for c in post["checks"]))
        verified = [e.payload for e in self.log.events() if e.kind == "write_verified"]
        self.assertEqual(len(verified), 1)
        self.assertTrue(verified[0]["verified"])
        self.assertIsNone(verified[0]["rolled_back"])

    def test_a_branch_that_fails_verification_is_rolled_back(self) -> None:
        counter = Path(self.tmp.name) / "runs"
        flaky = [sys.executable, "-c",
                 "import pathlib,sys; p=pathlib.Path(sys.argv[1]); "
                 "n=int(p.read_text()) if p.exists() else 0; p.write_text(str(n+1)); "
                 "sys.exit(0 if n == 0 else 1)", str(counter)]
        result = self.propose(test=flaky)
        self.assertEqual(result["outcome"], "verification_failed")
        post = result["post_action"]
        failed = [c["name"] for c in post["checks"] if not c["passed"]]
        self.assertEqual(failed, ["tests_pass_on_branch"])
        self.assertEqual(post["rollback"], {**post["rollback"], "attempted": True, "succeeded": True})
        self.assertNotIn("refs/heads/atlas/fix-readme", refs(self.root))
        self.assert_untouched()
        self.assertEqual(post["side_effects"][0]["undo"], "rolled back")
        verified = [e.payload for e in self.log.events() if e.kind == "write_verified"]
        self.assertEqual((verified[0]["verified"], verified[0]["rolled_back"]), (False, True))

    def proposal_on_disk(self) -> Proposal:
        from atlas_core.patch_proposal import discard
        proposal = prepare(str(self.root), FIX, "atlas/fix-readme", PASSES)
        git(self.root, "fetch", "-q", proposal.workdir, proposal.commit)
        discard(proposal)
        return proposal

    def test_rollback_leaves_a_branch_someone_moved(self) -> None:
        from atlas_core.patch_proposal import rollback
        proposal = self.proposal_on_disk()
        git(self.root, "update-ref", "refs/heads/atlas/fix-readme", self.base)
        self.assertFalse(rollback(proposal))
        self.assertEqual(git(self.root, "rev-parse", "atlas/fix-readme"), self.base)
        git(self.root, "update-ref", "refs/heads/atlas/fix-readme", proposal.commit, self.base)
        self.assertTrue(rollback(proposal))
        self.assertNotIn("atlas/fix-readme", refs(self.root))

    def test_verification_reads_the_repository_not_the_handlers_report(self) -> None:
        from atlas_core.patch_proposal import _repo_state, verify_created
        proposal = self.proposal_on_disk()
        before = _repo_state(str(self.root))
        checks, retest = verify_created(proposal, before)
        self.assertEqual([(c["name"], c["passed"], c["skipped"]) for c in checks], [
            ("ref_points_at_commit", False, False), ("parent_is_base", False, True),
            ("diff_is_approved", False, True), ("only_this_ref_changed", False, True),
            ("head_and_worktree_untouched", False, True), ("tests_pass_on_branch", False, True),
        ])
        self.assertIsNone(retest)
        git(self.root, "update-ref", "refs/heads/atlas/fix-readme", proposal.commit)
        git(self.root, "branch", "unrelated")
        (self.root / "stray").write_text("x")
        checks, _ = verify_created(proposal, before)
        failed = {c["name"] for c in checks if not c["passed"]}
        self.assertEqual(failed, {"only_this_ref_changed", "head_and_worktree_untouched"})


class TestNothingWritten(Repo):
    def test_a_wrong_answer_refuses(self) -> None:
        self.assertEqual(self.propose("yes")["outcome"], "refused")
        self.assertEqual(self.decisions(), ["requested", "refused"])
        self.assert_untouched()
        self.assert_no_clone_left()

    def test_nobody_to_ask_stops_at_approval_required(self) -> None:
        self.assertEqual(self.propose(None)["outcome"], "approval_required")
        self.assertEqual(self.decisions(), ["requested"])
        self.assert_untouched()

    def test_failing_tests_never_reach_a_person(self) -> None:
        result = self.propose(test=[sys.executable, "-c", "raise SystemExit(1)"])
        self.assertEqual(result["outcome"], "tests_failed")
        self.assertEqual(result["tests"]["exit_code"], 1)
        self.assertEqual(self.decisions(), [])
        self.assert_untouched()
        self.assert_no_clone_left()

    def test_head_moved_while_the_person_read(self) -> None:
        def move_then_approve(text: str) -> str:
            (self.root / "README.md").write_text("other\n")
            self.commit("two")
            return text.rsplit("operation  : ", 1)[1][:12]
        with self.assertRaises(ApprovalRejected) as caught:
            self.propose(move_then_approve)
        self.assertEqual(caught.exception.reason, "head_moved")
        self.assertNotIn("refs/heads/atlas/fix-readme", refs(self.root))
        self.assert_no_clone_left()

    def test_base_moved_after_the_approval_check_but_before_the_write(self) -> None:
        from unittest import mock
        import atlas_core.patch_proposal as module

        real_run = module.subprocess.run

        def move_main_then_run(argv: Any, *args: Any, **kwargs: Any) -> Any:
            if "--stdin" in argv:
                # Another process commits to main in the gap between consume()
                # and the ref transaction.
                (self.root / "README.md").write_text("other\n")
                self.commit("moved")
            return real_run(argv, *args, **kwargs)

        with mock.patch.object(module.subprocess, "run", move_main_then_run):
            with self.assertRaises(ProposalRefused) as caught:
                self.propose()
        self.assertIn("moved", str(caught.exception))
        self.assertNotIn("refs/heads/atlas/fix-readme", refs(self.root))
        finished = [e.payload["outcome"] for e in self.log.events() if e.kind == "call_finished"]
        self.assertEqual(finished, ["failed"])
        self.assertEqual(self.decisions(), ["requested", "granted", "consumed"])

    def test_a_detached_head_cannot_be_a_base(self) -> None:
        git(self.root, "checkout", "-q", "--detach")
        with self.assertRaises(ProposalRefused) as caught:
            self.propose()
        self.assertIn("detached", str(caught.exception))
        self.assert_no_clone_left()

    def test_transaction_inputs_cannot_carry_a_second_instruction(self) -> None:
        from atlas_core.patch_proposal import describe_create_branch
        good = {"repo": str(self.root), "branch": "atlas/x", "commit": self.base,
                "base": self.base, "base_ref": "refs/heads/main", "diff_sha256": "d",
                "source": "s"}
        describe_create_branch(good)
        for key, value in (("base_ref", "refs/heads/main\ndelete refs/heads/main"),
                           ("base_ref", "refs/heads/main x"), ("base_ref", "HEAD"),
                           ("base_ref", "refs/tags/v1"), ("commit", "HEAD"),
                           ("commit", self.base + "\ndelete refs/heads/main")):
            with self.subTest(key=key, value=value), self.assertRaises(ProposalRefused):
                describe_create_branch({**good, key: value})

    def test_a_branch_created_meanwhile_is_not_overwritten(self) -> None:
        def race_then_approve(text: str) -> str:
            git(self.root, "branch", "atlas/fix-readme", self.base)
            return text.rsplit("operation  : ", 1)[1][:12]
        with self.assertRaises(ProposalRefused):
            self.propose(race_then_approve)
        # The compare-and-swap refused: the branch still points where it was put.
        self.assertEqual(git(self.root, "rev-parse", "atlas/fix-readme"), self.base)

    def test_a_dirty_worktree_cannot_be_proposed_against(self) -> None:
        (self.root / "README.md").write_text("uncommitted\n")
        with self.assertRaises(ApprovalRejected) as caught:
            self.propose()
        self.assertEqual(caught.exception.reason, "state_unpinned")
        self.assert_no_clone_left()

    def test_an_existing_branch_is_refused_before_anything_runs(self) -> None:
        git(self.root, "branch", "atlas/fix-readme")
        with self.assertRaises(ProposalRefused):
            self.propose()


class TestRefusedInput(Repo):
    def patch_for(self, path: str, mode: str = "100644") -> bytes:
        return (f"diff --git a/{path} b/{path}\nnew file mode {mode}\n--- /dev/null\n"
                f"+++ b/{path}\n@@ -0,0 +1 @@\n+x\n").encode()

    def test_paths_outside_the_repository(self) -> None:
        for path in ("../outside", "a/../../outside", ".git/config", "sub/.GIT/hooks/x",
                     "/etc/passwd"):
            with self.subTest(path=path), self.assertRaises(ProposalRefused):
                self.propose(patch=self.patch_for(path))
        self.assertFalse((self.root.parent / "outside").exists())
        self.assert_untouched()
        self.assert_no_clone_left()

    def test_symlinks_and_submodules(self) -> None:
        for mode in ("120000", "160000"):
            with self.subTest(mode=mode), self.assertRaises(ProposalRefused):
                self.propose(patch=self.patch_for("link", mode))
        self.assert_untouched()

    def test_a_path_through_an_existing_symlink(self) -> None:
        import os

        outside = Path(self.tmp.name) / "outside"
        outside.mkdir()
        os.symlink(outside, self.root / "link")
        git(self.root, "add", "link")
        self.commit("link")
        self.base = git(self.root, "rev-parse", "HEAD")
        self.before = refs(self.root)
        with self.assertRaises(ProposalRefused):
            self.propose(patch=self.patch_for("link/evil"))
        self.assertEqual(list(outside.iterdir()), [])
        self.assert_untouched()

    def test_branch_names(self) -> None:
        for name in ("main", "feature/x", "atlas/", "atlas/X", "atlas/a..b", "atlas/a.lock",
                     "atlas/a;touch pwned", "atlas/a b", "refs/heads/atlas/x", "atlas/a/b"):
            with self.subTest(name=name), self.assertRaises(ProposalRefused):
                validate_branch(name)

    def test_no_shell_ever_reads_the_test_command_or_the_patch(self) -> None:
        pwned = self.root.parent / "pwned"
        result = self.propose(test=["true;", "touch", str(pwned)])
        self.assertEqual(result["outcome"], "tests_failed")
        content = b"""diff --git a/README.md b/README.md
--- a/README.md
+++ b/README.md
@@ -1 +1 @@
-broken
+fixed $(touch %s) `touch %s`
""" % (str(pwned).encode(), str(pwned).encode())
        self.assertEqual(self.propose(patch=content)["outcome"], "branch_created")
        self.assertFalse(pwned.exists())

    def test_empty_and_oversized_patches(self) -> None:
        for patch in (b"", b"   \n", b"x" * (256 * 1024 + 1)):
            with self.subTest(size=len(patch)), self.assertRaises(ProposalRefused):
                self.propose(patch=patch)


class TestCli(Repo):
    def run_cli(self, *args: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(list(args))
        return code, out.getvalue(), err.getvalue()

    def test_no_input_stops_at_approval_required_with_exit_3(self) -> None:
        patch = Path(self.tmp.name) / "fix.patch"
        patch.write_bytes(FIX)
        log = Path(self.tmp.name) / "events.jsonl"
        code, out, _ = self.run_cli(
            "propose", "--repo", str(self.root), "--patch", str(patch),
            "--branch", "atlas/fix-readme", "--test", " ".join(PASSES[:2]) + ' "' + PASSES[2] + '"',
            "--event-log", str(log), "--no-input", "--json")
        self.assertEqual(code, 3)
        self.assertEqual(json.loads(out)["outcome"], "approval_required")
        kinds = [json.loads(line)["kind"] for line in log.read_text().splitlines()]
        self.assertEqual(kinds, ["approval_recorded"])
        self.assert_untouched()

    def test_refused_input_is_exit_1(self) -> None:
        patch = Path(self.tmp.name) / "fix.patch"
        patch.write_bytes(FIX)
        code, _, err = self.run_cli(
            "propose", "--repo", str(self.root), "--patch", str(patch),
            "--branch", "main", "--test", "true", "--no-input")
        self.assertEqual(code, 1)
        self.assertIn("branch must match", err)
        self.assert_untouched()


if __name__ == "__main__":
    unittest.main()
