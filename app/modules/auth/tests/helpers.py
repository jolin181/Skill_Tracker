from app.core.config import settings

API = settings.api_v1_prefix
PASSWORD = "Correct-Horse-9"


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
