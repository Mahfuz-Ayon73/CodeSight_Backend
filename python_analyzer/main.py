"""
FastAPI Microservice for CodeSight Analysis Engine
Provides REST endpoints for Spring Boot backend to trigger codebase analysis.
"""

import asyncio
import functools
import os
import tempfile
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
import uvicorn

from analyzer import run_analysis


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class AnalysisRequest(BaseModel):
    project_id: str = Field(..., description="UUID of the project")
    repo_path: str = Field(..., description="Absolute path to the codebase directory")
    output_dir: Optional[str] = Field(None, description="Output directory (optional, defaults to temp)")
    purge_source: bool = Field(True, description="Whether to delete source files after analysis")


class AnalysisResponse(BaseModel):
    success: bool
    project_id: str
    blueprint_path: Optional[str] = None
    error_message: Optional[str] = None
    execution_time_seconds: Optional[float] = None


class HealthResponse(BaseModel):
    status: str
    version: str
    dependencies: dict


# ---------------------------------------------------------------------------
# App instance
# ---------------------------------------------------------------------------

app = FastAPI(
    title="CodeSight Analysis Engine",
    description="FastAPI microservice for analyzing JavaScript/TypeScript codebases",
    version="1.0.0",
)

# In-memory task tracking (for production, use Redis/DB)
analysis_tasks: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint with dependency status."""
    deps = {
        "tree_sitter": _check_import("tree_sitter"),
        "networkx": _check_import("networkx"),
        "numpy": _check_import("numpy"),
        "scikit_learn": _check_import("sklearn"),
        "sentence_transformers": _check_import("sentence_transformers"),
        "hdbscan": _check_import("hdbscan"),
        "leidenalg": _check_import("leidenalg"),  # Optional
        "igraph": _check_import("igraph"),        # Optional
    }
    
    return HealthResponse(
        status="healthy",
        version="1.0.0",
        dependencies=deps,
    )


@app.post("/analyze", response_model=AnalysisResponse)
async def trigger_analysis(
    request: AnalysisRequest,
    background_tasks: BackgroundTasks,
):
    """
    Trigger codebase analysis asynchronously.
    Returns immediately with task tracking info.
    """
    task_id = str(uuid.uuid4())
    
    # Validate repo path
    repo_path = Path(request.repo_path)
    if not repo_path.exists() or not repo_path.is_dir():
        raise HTTPException(
            status_code=400,
            detail=f"Repository path does not exist: {request.repo_path}"
        )
    
    # Default output directory
    if request.output_dir:
        output_dir = Path(request.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
    else:
        output_dir = Path(tempfile.mkdtemp(prefix="codesight_analysis_"))
    
    # Track task
    analysis_tasks[task_id] = {
        "project_id": request.project_id,
        "status": "queued",
        "stage": "queued",
        "message": "Waiting to start...",
        "repo_path": str(repo_path),
        "output_dir": str(output_dir),
        "purge_source": request.purge_source,
    }
    
    # Run analysis in background
    background_tasks.add_task(
        _run_analysis_task,
        task_id,
        request.project_id,
        str(repo_path),
        str(output_dir),
        request.purge_source,
    )
    
    return AnalysisResponse(
        success=True,
        project_id=request.project_id,
        blueprint_path=str(output_dir / "graph_blueprint.json"),
    )


@app.get("/analyze/{project_id}/status")
async def get_analysis_status(project_id: str):
    """Get the status of an analysis task by project ID."""
    # Find task by project_id
    task_info = None
    task_id = None
    for tid, info in analysis_tasks.items():
        if info["project_id"] == project_id:
            task_info = info
            task_id = tid
            break
    
    if not task_info:
        raise HTTPException(status_code=404, detail=f"No analysis found for project: {project_id}")
    
    return {
        "task_id": task_id,
        "project_id": project_id,
        "status": task_info["status"],
        "stage": task_info.get("stage"),
        "message": task_info.get("message"),
        "blueprint_path": task_info.get("blueprint_path"),
        "error_message": task_info.get("error_message"),
        "execution_time_seconds": task_info.get("execution_time_seconds"),
    }


@app.post("/analyze/sync", response_model=AnalysisResponse)
async def analyze_sync(request: AnalysisRequest):
    """
    Synchronous analysis endpoint (blocks until completion).
    Use for small codebases or when immediate results are needed.
    """
    import time
    
    # Validate repo path
    repo_path = Path(request.repo_path)
    if not repo_path.exists() or not repo_path.is_dir():
        raise HTTPException(
            status_code=400,
            detail=f"Repository path does not exist: {request.repo_path}"
        )
    
    # Default output directory
    if request.output_dir:
        output_dir = Path(request.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
    else:
        output_dir = Path(tempfile.mkdtemp(prefix="codesight_sync_"))
    
    try:
        start_time = time.time()
        
        # Run analysis synchronously
        blueprint_path = run_analysis(
            repo_root=str(repo_path),
            output_dir=str(output_dir),
            project_id=request.project_id,
            purge_after=request.purge_source,
        )
        
        execution_time = round(time.time() - start_time, 2)
        
        return AnalysisResponse(
            success=True,
            project_id=request.project_id,
            blueprint_path=blueprint_path,
            execution_time_seconds=execution_time,
        )
        
    except Exception as e:
        return AnalysisResponse(
            success=False,
            project_id=request.project_id,
            error_message=str(e),
        )


# ---------------------------------------------------------------------------
# Background task runner
# ---------------------------------------------------------------------------

async def _run_analysis_task(
    task_id: str,
    project_id: str,
    repo_path: str,
    output_dir: str,
    purge_source: bool,
):
    """Background task to run the analysis."""
    import time

    # Update status
    analysis_tasks[task_id]["status"] = "running"

    def _progress(stage: str, message: str) -> None:
        analysis_tasks[task_id]["stage"] = stage
        analysis_tasks[task_id]["message"] = message

    try:
        start_time = time.time()

        # Run analysis in thread pool to avoid blocking asyncio
        loop = asyncio.get_event_loop()
        blueprint_path = await loop.run_in_executor(
            None,
            functools.partial(
                run_analysis,
                repo_path,
                output_dir,
                project_id,
                purge_source,
                _progress,
            ),
        )

        execution_time = round(time.time() - start_time, 2)

        # Update task with success
        analysis_tasks[task_id].update({
            "status": "completed",
            "blueprint_path": blueprint_path,
            "execution_time_seconds": execution_time,
        })

    except Exception as e:
        # Update task with error
        analysis_tasks[task_id].update({
            "status": "failed",
            "stage": "failed",
            "error_message": str(e),
        })


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def _check_import(module_name: str) -> dict:
    """Check if a module can be imported and return status."""
    try:
        __import__(module_name)
        return {"available": True, "error": None}
    except ImportError as e:
        return {"available": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    
    # Configuration
    host = os.getenv("FASTAPI_HOST", "127.0.0.1")
    port = int(os.getenv("FASTAPI_PORT", "8000"))
    log_level = os.getenv("FASTAPI_LOG_LEVEL", "info")
    
    print(f"Starting CodeSight Analysis Engine on {host}:{port}")
    print(f"Log level: {log_level}")
    
    # Check critical dependencies
    critical_deps = ["tree_sitter", "networkx", "numpy", "sklearn", "sentence_transformers"]
    missing_deps = []
    
    for dep in critical_deps:
        result = _check_import(dep)
        if not result["available"]:
            missing_deps.append(f"{dep}: {result['error']}")
    
    if missing_deps:
        print("ERROR: Missing critical dependencies:")
        for dep in missing_deps:
            print(f"  - {dep}")
        print("\nRun: pip install -r requirements.txt")
        sys.exit(1)
    
    # Check optional dependencies
    optional_deps = ["leidenalg", "igraph", "hdbscan"]
    for dep in optional_deps:
        result = _check_import(dep)
        status = "✓" if result["available"] else "✗ (fallback enabled)"
        print(f"Optional dependency {dep}: {status}")
    
    print("\nAll systems ready. Starting server...\n")
    
    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        log_level=log_level,
        reload=False,  # Set to True for development
    )