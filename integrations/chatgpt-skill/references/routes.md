# Atlas Core Routes

Generated from `atlas_core.router.ROUTES`. Regenerate this package after route changes.

| Route | Risk | Steps |
| --- | --- | --- |
| `repo_review` | medium | observe_repo -> summarize -> find_gaps -> prioritize -> recommend_pr_slices |
| `architecture_decision` | high | requirements -> high_level_design -> risk_review -> options_analysis -> recommendation |
| `root_cause` | medium | problem -> symptoms_vs_causes -> causal_chain -> root_cause -> actions |
| `decision_tradeoff` | medium | context -> options -> tradeoffs -> recommendation -> next_step |
| `learning` | low | simple_explanation -> common_confusion -> example -> understanding_check |
| `prompt_improvement` | low | diagnose_prompt -> identify_failure_modes -> rewrite_structure -> test_cases |
| `general` | low | understand -> answer -> next_step |

Inspect the live route map with:

```bash
atlas routes
```
