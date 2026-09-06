"""
Candy-Man Backend FastAPI Server
Provides POST /scan matching API_CONTRACT.md. Orchestration only -- every
analysis algorithm lives in engine/*.py.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from engine.candidacy import count_all_functions, extract_candidate_functions
from engine.repo_loader import RepoLoadError, load_repository
from engine.scorer import rank_and_format_results
from engine.structural import compute_structural_score
from engine.transformation import compute_transformation_score
from models import ErrorResponse, ScanRequest, ScanResponse

app = FastAPI(title="Candy-Man API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def run_pipeline(target: str, target_type: str) -> dict:
    """Runs the full Step 0 -> Step 5 pipeline for one scan request and
    returns a dict matching ScanResponse. Raises RepoLoadError on failure so
    the route can translate it into the documented error response."""
    loaded = load_repository(target, target_type)
    try:
        total_scanned = count_all_functions(loaded.parsed_files)
        candidates = extract_candidate_functions(loaded.parsed_files, loaded.local_top_level)

        scored_candidates = []
        for candidate in candidates:
            structural_result = compute_structural_score(candidate)
            transformation_result = compute_transformation_score(candidate)
            evidence_lines = set(structural_result["evidence_lines"]) | set(
                transformation_result["evidence_lines"]
            )
            scored_candidates.append(
                {
                    "function_name": candidate.qualname,
                    "file": candidate.file,
                    "def_line": candidate.def_line,
                    "evidence_lines": sorted(evidence_lines),
                    "r_structural": structural_result["r_structural"],
                    "transformation_score": transformation_result["transformation_score"],
                    "transformation_computed": transformation_result["transformation_computed"],
                }
            )

        return rank_and_format_results(
            repo=target,
            total_scanned=total_scanned,
            candidates=scored_candidates,
            unscannable_files=loaded.unscannable_files,
        )
    finally:
        loaded.cleanup()


@app.post(
    "/scan",
    response_model=ScanResponse,
    responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)
async def scan_repository(request: ScanRequest):
    """Scans a local path or GitHub repository for wrapper functions."""
    try:
        result = run_pipeline(request.target, request.type)
        return ScanResponse(**result)
    except RepoLoadError as exc:
        return JSONResponse(
            status_code=400,
            content=ErrorResponse(error=exc.code, message=exc.message).model_dump(),
        )
    except Exception as exc:  # last-resort guard: a scan must never 500 with a bare traceback
        return JSONResponse(
            status_code=500,
            content=ErrorResponse(
                error="scan_failed",
                message=f"An unexpected error occurred while scanning: {exc}",
            ).model_dump(),
        )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
