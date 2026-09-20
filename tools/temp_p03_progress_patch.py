"""One-time guarded controller patch; delete before merging."""
from pathlib import Path
p=Path('atlas_core/controller.py')
s=p.read_text(encoding='utf-8')
old='''            state.evaluations.append(evaluation)
            if expired():
                break
            if (
                evaluation.requires_user_approval
'''
new='''            state.evaluations.append(evaluation)
            if expired():
                break
            # In bounded runs, two identical unsuccessful model outputs with
            # no new observation establish that another call is unproductive.
            # Legacy unbudgeted verdict semantics remain unchanged.
            if (
                budget is not None
                and self.model_adapter is not None
                and len(state.outputs) >= 2
                and state.outputs[-1] == state.outputs[-2]
                and evaluation.retry_is_possible
                and not evaluation.blocked_by
            ):
                state.metadata["no_progress"] = {
                    "reason": "identical_model_output",
                    "iterations": [state.iteration - 1, state.iteration],
                }
                state.stop("no_progress")
                break
            if (
                evaluation.requires_user_approval
'''
assert s.count(old)==1,s.count(old)
p.write_text(s.replace(old,new),encoding='utf-8')
