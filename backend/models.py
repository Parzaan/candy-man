from typing import List, Literal, Optional
from pydantic import BaseModel, Field

class ScanRequest(BaseModel):
    target: str = Field(..., description="Local directory path or GitHub repository URL")
    type: Literal["local", "github"] = Field(..., description="Target repository type")

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
