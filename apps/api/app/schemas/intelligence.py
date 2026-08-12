from typing import Literal

from pydantic import BaseModel, Field, model_validator


class CandidateEvaluationRequest(BaseModel):
    portfolio_id: str
    action: Literal["add", "reduce", "remove"] = "add"
    target_weight: float | None = Field(default=None, ge=0, le=1)
    sizing: Literal["manual", "optimizer"] = "manual"

    @model_validator(mode="after")
    def validate_action(self):
        if self.action == "remove" and self.target_weight not in (None, 0):
            raise ValueError("remove requires a zero or omitted target_weight")
        if self.sizing == "manual" and self.action != "remove" and self.target_weight is None:
            raise ValueError("manual add/reduce requires target_weight")
        return self


class SaveCandidateProposalRequest(CandidateEvaluationRequest):
    label: str = Field(default="Security decision proposal", min_length=1, max_length=160)
