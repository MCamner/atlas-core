from __future__ import annotations

WRITE_KEYWORDS = [
    "commit", "push", "merge", "delete", "remove file", "radera", "ta bort",
    "skapa issue", "create issue", "open pr", "öppna pr", "create pull request",
    "ändra fil", "edit file", "write file", "skriv till", "publicera",
]

def requires_write_approval(task: str) -> bool:
    text = task.lower()
    return any(keyword in text for keyword in WRITE_KEYWORDS)

def safety_notice(task: str) -> str | None:
    if requires_write_approval(task):
        return (
            "Task verkar innehålla en write-åtgärd. Atlas Core är read-only by default "
            "och ska be om explicit godkännande innan branch, commit, PR, issue eller filändring."
        )
    return None
