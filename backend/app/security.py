import hashlib, hmac, secrets, time
from .config import settings

def make_otp(session_id: str, now: int | None = None) -> str:
    now = now or int(time.time())
    bucket = now // settings.otp_ttl_seconds
    digest = hmac.new(settings.otp_secret.encode(), f"{session_id}:{bucket}".encode(),
                      hashlib.sha256).hexdigest()
    return str(int(digest[:8], 16) % 1_000_000).zfill(6)

def verify_otp(session_id: str, supplied: str, now: int | None = None) -> bool:
    now = now or int(time.time())
    return hmac.compare_digest(supplied, make_otp(session_id, now))

def new_mock_session() -> str:
    return "demo-" + secrets.token_urlsafe(18)
