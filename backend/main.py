import time

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

MAX_SNIPPET_LINES = 15


@app.get("/")
async def root():
    return {"status": "Candy-Man API is running", "docs": "/docs"}


def _extract_snippet(candidate, evidence_lines):
    """A small, honest source excerpt: from the function's def line through
    the last evidence line (capped at MAX_SNIPPET_LINES so a huge function
    doesn't dump its entire body). No fabricated annotations, no injected
    comments -- exactly what's in the file."""
    lines = candidate.source.splitlines()
    start = candidate.def_line
    end = max(evidence_lines) if evidence_lines else candidate.def_line
    end = min(end, start + MAX_SNIPPET_LINES - 1)
    snippet_lines = lines[start - 1:end]
    return "\n".join(snippet_lines), start


def run_pipeline(target: str, target_type: str) -> dict:
    start_time = time.monotonic()
    loaded = load_repository(target, target_type)
    try:
        total_scanned = count_all_functions(loaded.parsed_files)
        total_loc = sum(len(pf.source.splitlines()) for pf in loaded.parsed_files)
        candidates = extract_candidate_functions(loaded.parsed_files, loaded.local_top_level)

        scored_candidates = []
        for candidate in candidates:
            structural_result = compute_structural_score(candidate)
            transformation_result = compute_transformation_score(candidate)
            evidence_lines = sorted(
                set(structural_result["evidence_lines"]) | set(transformation_result["evidence_lines"])
            )
            snippet, snippet_start = _extract_snippet(candidate, evidence_lines)
            scored_candidates.append(
                {
                    "function_name": candidate.qualname,
                    "file": candidate.file,
                    "def_line": candidate.def_line,
                    "evidence_lines": evidence_lines,
                    "r_structural": structural_result["r_structural"],
                    "transformation_score": transformation_result["transformation_score"],
                    "transformation_computed": transformation_result["transformation_computed"],
                    "source_snippet": snippet,
                    "snippet_start_line": snippet_start,
                }
            )

        result = rank_and_format_results(
            repo=target,
            total_scanned=total_scanned,
            candidates=scored_candidates,
            unscannable_files=loaded.unscannable_files,
        )

        # Every scored candidate, flagged or not -- powers the scatter plot,
        # which needs the full population to show what "both signals low"
        # actually looks like relative to everything else.
        result["all_candidates"] = [
            {
                "function_name": c["function_name"],
                "file": c["file"],
                "def_line": c["def_line"],
                "r_structural": c["r_structural"],
                "transformation_score": c["transformation_score"],
                "transformation_computed": c["transformation_computed"],
            }
            for c in scored_candidates
        ]
        result["total_loc"] = total_loc
        result["scan_duration_seconds"] = round(time.monotonic() - start_time, 2)
        return result
    finally:
        loaded.cleanup()


@app.post(
    "/scan",
    response_model=ScanResponse,
    responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)
async def scan_repository(request: ScanRequest):
    try:
        result = run_pipeline(request.target, request.type)
        return ScanResponse(**result)
    except RepoLoadError as exc:
        return JSONResponse(
            status_code=400,
            content=ErrorResponse(error=exc.code, message=exc.message).model_dump(),
        )
    except Exception as exc:
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