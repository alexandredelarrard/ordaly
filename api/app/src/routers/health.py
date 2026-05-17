from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/")
async def root():
    return {"message": "OK"}


@router.get("/health")
async def health():
    return {"status": "healthy"}
