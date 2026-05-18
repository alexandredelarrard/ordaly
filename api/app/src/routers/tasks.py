import logging

from celery.result import AsyncResult
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from src.celery.celery_app import celery
from src.schemas.tasks import TaskStatusResponse

router = APIRouter(prefix="/v1", tags=["tasks"])
logger = logging.getLogger(__name__)


class TaskIdBody(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    task_id: str = Field(..., alias="taskid")


@router.post("/tasks/status", response_model=TaskStatusResponse)
async def task_status(
    body: TaskIdBody
):
    """Poll Celery task result (requires Bearer JWT)."""
    task = AsyncResult(body.task_id, app=celery)
    try:
        if task.state == "PENDING":
            return TaskStatusResponse(
                task_id=body.task_id, state=task.state, status="Pending..."
            )
        if task.state == "SUCCESS":
            return TaskStatusResponse(
                task_id=body.task_id, state=task.state, result=task.result
            )
        return TaskStatusResponse(
            task_id=body.task_id, state=task.state, status=str(task.info)
        )
    except Exception as exc:
        logger.exception("task_status failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc
