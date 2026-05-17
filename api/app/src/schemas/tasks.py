from typing import Any, Optional

from pydantic import BaseModel, Field


class TaskStatusResponse(BaseModel):
    task_id: str
    state: str
    status: Optional[str] = None
    result: Optional[Any] = None
