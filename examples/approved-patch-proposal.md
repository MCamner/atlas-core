# Example: Human-Approved Patch Proposal

This is a separate, explicit write workflow. A read-only review does not
automatically create or apply a patch.

1. Start from a clean local branch and prepare a patch file without applying it
   to the target checkout.
2. Read the complete patch and choose a test command that is safe to run under
   your own OS account. `atlas propose` runs the test command without a shell,
   but it is not a sandbox.
3. Ask Core to stage and verify the proposal in a shared clone:

   ```sh
   atlas propose --repo /path/to/repo \
     --patch /path/to/change.patch \
     --branch atlas/fix-observation-bound \
     --test "python -m unittest discover -s tests"
   ```

4. Review the diff and test result printed by Core. Type the operation digest
   only when the exact change is approved. With no interactive terminal, the
   operation is refused and no branch is created.
5. Inspect the resulting `atlas/*` branch and its post-action checks. Push and
   merge, if appropriate, remain separate operator actions.

If verification fails, Core attempts to remove the created branch using a
compare-and-swap. Test side effects and fetched Git objects are not reversible;
see [the write contract](../docs/api-contract.md#write-boundary).
