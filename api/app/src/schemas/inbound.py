from pydantic import BaseModel, Field


class InboundEmailAccepted(BaseModel):
    status: str = Field(..., description="Acknowledgement status")
    message: str
    saved: list[str] = Field(default_factory=list, description="Basenames of stored PDFs")
    task_ids: list[str] = Field(
        default_factory=list,
        description="Celery task ids for async PDF parsing (empty if enqueue failed or no PDFs)",
    )
