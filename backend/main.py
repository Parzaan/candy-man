"""
Candy-Man Backend FastAPI Server
Provides POST /scan route matching API_CONTRACT.md schema.
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from models import ScanRequest, ScanResponse, ErrorResponse

app = FastAPI(title="Candy-Man API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/scan", response_model=ScanResponse, responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}})
async def scan_repository(request: ScanRequest):
    """
    Scans a local path or GitHub repository for wrapper functions.
    """
    # TODO: Wire repo_loader -> candidacy -> structural -> transformation -> scorer
    return ScanResponse(
        repo=request.target,
        total_functions_scanned=0,
        candidates_considered=0,
        unscannable_files=[],
        flagged=[]
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
