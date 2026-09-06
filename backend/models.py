from typing import List
from pydantic import BaseModel


class ScanRequest(BaseModel):
    target: str
    type: str  # "local" | "github"


class FlaggedFunction(BaseModel):
    function_name: str
    file: str
    def_line: int
    evidence_lines: List[int]
    r_structural: float
    transformation_score: float
    transformation_computed: bool
    suspicion_rank: int


class ScanResponse(BaseModel):
    repo: str
    total_functions_scanned: int
    candidates_considered: int
    unscannable_files: List[str]
    flagged: List[FlaggedFunction]


class ErrorResponse(BaseModel):
    error: str
    message: str