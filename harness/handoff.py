from typing import List, Dict, Any
from pydantic import BaseModel, Field


class HandoffReport(BaseModel):
    """Handoff report for human support escalation."""
    status: str = Field(description="Trigger status code for handoff")
    current_stage: str = Field(description="Stage or turn where issue occurred")
    actions_taken: List[Dict[str, Any]] = Field(default_factory=list, description="History of executed steps")
    failed_attempts: List[str] = Field(default_factory=list, description="Warnings or failed attempts")
    specific_question: str = Field(description="Specific actionable question or request for human agent")

    def format_terminal(self) -> str:
        """Format the report cleanly for terminal CLI display."""
        sep = "=" * 62
        lines = [
            f"\n{sep}",
            "              HUMAN HANDOFF REPORT                    ",
            sep,
            f" [Status]           : {self.status}",
            f" [Stage]            : {self.current_stage}",
            f" [Actions Taken]    : {len(self.actions_taken)} step(s)",
            f" [Intervention]     : {', '.join(self.failed_attempts) if self.failed_attempts else 'None'}",
            f" [Specific Request] : {self.specific_question}",
            sep,
        ]
        return "\n".join(lines)
