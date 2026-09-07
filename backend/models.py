from typing import List
from pydantic import BaseModel


class ScanRequest(BaseModel):
    target: str
    type: str  # "local" | "github"


class CandidateScore(BaseModel):
    """Every scored candidate, whether flagged or not -- powers the
    scatter plot, which needs the full population, not just the flagged
    subset."""
    function_name: str
    file: str
    def_line: int
    r_structural: float
    transformation_score: float
    transformation_computed: bool


class FlaggedFunction(BaseModel):
    function_name: str
    file: str
    def_line: int
    evidence_lines: List[int]
    r_structural: float
    transformation_score: float
    transformation_computed: bool
    suspicion_rank: int
    source_snippet: str
    snippet_start_line: int


class ScanResponse(BaseModel):
    repo: str
    total_functions_scanned: int
    candidates_considered: int
    total_loc: int
    scan_duration_seconds: float
    unscannable_files: List[str]
    flagged: List[FlaggedFunction]
    all_candidates: List[CandidateScore]


class ErrorResponse(BaseModel):
    error: str
    message: str