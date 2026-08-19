from fastapi import APIRouter

router = APIRouter(tags=["Status"])


@router.get("/status")
def get_status() -> dict[str, str]:
    return {"status": "ok"}
