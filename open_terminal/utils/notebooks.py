"""Jupyter notebook execution endpoints.

Provides per-cell execution with multi-session support. Each session gets its
own Jupyter kernel via nbclient. Requires the ``notebooks`` optional extra::

    pip install open-terminal[notebooks]
"""

import asyncio
import json
import os
import time
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

import nbformat
from nbclient import NotebookClient

from open_terminal.dependencies import get_filesystem, verify_api_key
from open_terminal.env import sanitized_environ
from open_terminal.utils.fs import UserFS


# ---------------------------------------------------------------------------
# Session manager
# ---------------------------------------------------------------------------

_IDLE_TIMEOUT = 30 * 60  # 30 minutes


class _Session:
    """Wraps a NotebookClient for a specific notebook."""

    __slots__ = ("id", "path", "nb", "client", "owner", "busy", "created_at", "last_used")

    def __init__(self, session_id: str, path: str, nb, client, owner: str):
        self.id = session_id
        self.path = path
        self.nb = nb
        self.client = client
        self.owner = owner
        self.busy = False
        self.created_at = time.time()
        self.last_used = time.time()


_sessions: dict[str, _Session] = {}
_cleanup_task: Optional[asyncio.Task] = None


async def _idle_cleanup_loop():
    """Periodically remove sessions idle for more than _IDLE_TIMEOUT."""
    while True:
        await asyncio.sleep(60)
        now = time.time()
        stale = [
            sid
            for sid, s in _sessions.items()
            if now - s.last_used > _IDLE_TIMEOUT and not s.busy
        ]
        for sid in stale:
            await _destroy_session(sid)


async def _close_client(client):
    try:
        await client._async_cleanup_kernel()
    except Exception:
        # A failed handshake can leave only the manager initialized.
        try:
            if client.km and await client.km.is_alive():
                await client.km.shutdown_kernel(now=True)
        except Exception:
            pass
        finally:
            if client.kc:
                client.kc.stop_channels()


async def _destroy_session(session_id):
    session = _sessions.pop(session_id, None)
    if session and session.client:
        await _close_client(session.client)


def _ensure_cleanup_task():
    global _cleanup_task
    if _cleanup_task is None or _cleanup_task.done():
        _cleanup_task = asyncio.create_task(_idle_cleanup_loop())


async def shutdown_notebooks():
    global _cleanup_task
    if _cleanup_task:
        _cleanup_task.cancel()
        await asyncio.gather(_cleanup_task, return_exceptions=True)
        _cleanup_task = None
    await asyncio.gather(*(_destroy_session(sid) for sid in list(_sessions)), return_exceptions=True)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class CreateSessionRequest(BaseModel):
    path: str = Field(..., description="Absolute path to the .ipynb file.")


class CreateSessionResponse(BaseModel):
    id: str
    kernel: str
    status: str


class ExecuteCellRequest(BaseModel):
    cell_index: int = Field(..., description="Zero-based cell index to execute.")
    source: Optional[str] = Field(
        None, description="Override cell source. If omitted, uses the source already in the notebook."
    )


class ExecuteCellResponse(BaseModel):
    status: str
    execution_count: Optional[int] = None
    outputs: list = Field(default_factory=list)


class SessionStatusResponse(BaseModel):
    id: str
    path: str
    kernel: str
    status: str


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


router = APIRouter(
    prefix="/notebooks",
    tags=["notebooks"],
    dependencies=[Depends(verify_api_key), Depends(get_filesystem)],
)


def owned_session(session_id: str, request: Request) -> _Session:
    session = _sessions.get(session_id)
    if not session or session.owner != request.headers.get("x-user-id", ""):
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.post(
    "",
    response_model=CreateSessionResponse,
    operation_id="create_notebook_session",
    summary="Create a notebook session",
    description="Start a Jupyter kernel for the given notebook. Returns a session ID for subsequent execute calls.",
    include_in_schema=False,
)
async def create_session(req: CreateSessionRequest, request: Request, fs: UserFS = Depends(get_filesystem)):

    _ensure_cleanup_task()

    path = fs.resolve_path(req.path)
    if not await fs.isfile(path):
        raise HTTPException(status_code=404, detail=f"Notebook not found: {path}")

    # Read and parse the notebook
    content = await fs.read_text(path)

    try:
        nb = nbformat.reads(content, as_version=4)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid notebook: {e}")

    kernel_name = nb.metadata.get("kernelspec", {}).get("name", "python3")

    # Start kernel — follow nbclient's setup_kernel pattern
    client = NotebookClient(nb, kernel_name=kernel_name, timeout=120)
    try:
        km = client.create_kernel_manager()
        kernel_env = sanitized_environ()
        if fs.username:
            km.connection_file = f"/tmp/open-terminal-kernel-{uuid.uuid4().hex}.json"
            # Jupyter writes the connection file before launching this command.
            # Keep server ownership for cleanup; grant only the user's group read access.
            km.kernel_spec.argv = [
                "sh", "-c",
                'sudo -n chgrp "$1" "$2" && chmod 640 "$2" && shift 2 && exec "$@"',
                "--", fs.username, "{connection_file}",
                "sudo", "-n", "-E", "-u", fs.username, "--", "env",
                f"HOME={fs.home}", f"USER={fs.username}", f"LOGNAME={fs.username}",
                f"PATH={kernel_env.get('PATH', os.defpath)}", *km.format_kernel_cmd(),
            ]
        await client.async_start_new_kernel(env=kernel_env, cwd=fs.home)
        await client.async_start_new_kernel_client()
    except BaseException as e:
        await _close_client(client)
        if isinstance(e, asyncio.CancelledError):
            raise
        raise HTTPException(
            status_code=500,
            detail=f"Failed to start kernel '{kernel_name}': {e}",
        )

    session_id = uuid.uuid4().hex[:12]
    _sessions[session_id] = _Session(session_id, path, nb, client, request.headers.get("x-user-id", ""))

    return CreateSessionResponse(
        id=session_id, kernel=kernel_name, status="ready"
    )


@router.post(
    "/{session_id}/execute",
    response_model=ExecuteCellResponse,
    operation_id="execute_notebook_cell",
    summary="Execute a notebook cell",
    description="Execute a single cell in the given session. Optionally override the cell source. "
    "Updates the .ipynb file in place after execution.",
    include_in_schema=False,
)
async def execute_cell(
    req: ExecuteCellRequest,
    session: _Session = Depends(owned_session),
    fs: UserFS = Depends(get_filesystem),
):
    if session.busy:
        raise HTTPException(status_code=409, detail="Cell already executing")

    nb = session.nb
    if req.cell_index < 0 or req.cell_index >= len(nb.cells):
        raise HTTPException(
            status_code=400,
            detail=f"cell_index {req.cell_index} out of range (0..{len(nb.cells) - 1})",
        )

    cell = nb.cells[req.cell_index]
    if req.source is not None:
        cell.source = req.source

    session.busy = True
    session.last_used = time.time()

    try:
        await session.client.async_execute_cell(cell, req.cell_index)
    except asyncio.CancelledError:
        await _destroy_session(session.id)
        raise
    except Exception as e:
        # Return the error as a cell output rather than HTTP error
        return ExecuteCellResponse(
            status="error",
            outputs=[
                {
                    "output_type": "error",
                    "ename": type(e).__name__,
                    "evalue": str(e),
                    "traceback": [str(e)],
                }
            ],
        )

    finally:
        session.busy = False
    session.last_used = time.time()

    # Serialize outputs
    outputs = []
    for o in cell.outputs:
        od = dict(o)
        if "data" in od:
            od["data"] = dict(od["data"])
        outputs.append(od)

    ec = cell.get("execution_count")

    # Save notebook to disk
    try:
        nb_json = nbformat.writes(nb)
        await fs.write(session.path, nb_json)
    except Exception:
        pass  # non-fatal

    return ExecuteCellResponse(
        status="ok", execution_count=ec, outputs=outputs
    )


@router.get(
    "/{session_id}",
    response_model=SessionStatusResponse,
    operation_id="get_notebook_session",
    summary="Get notebook session status",
    include_in_schema=False,
)
async def get_session(session: _Session = Depends(owned_session)):

    kernel_name = session.nb.metadata.get("kernelspec", {}).get(
        "name", "python3"
    )
    status = "busy" if session.busy else "ready"
    return SessionStatusResponse(
        id=session.id, path=session.path, kernel=kernel_name, status=status
    )


@router.delete(
    "/{session_id}",
    operation_id="delete_notebook_session",
    summary="Stop a notebook session",
    include_in_schema=False,
)
async def delete_session(session: _Session = Depends(owned_session)):
    await _destroy_session(session.id)
    return {"status": "stopped"}
