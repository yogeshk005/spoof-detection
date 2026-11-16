import re
from pydantic import BaseModel, Field, field_validator

class EnrollStart(BaseModel):
    credential_id: str = Field(min_length=3, max_length=120, pattern=r"^[A-Za-z0-9_-]+$")
    display_name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=5, max_length=320)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", normalized):
            raise ValueError("Enter a valid email address.")
        return normalized

class VerifyStart(BaseModel):
    credential_id: str = Field(min_length=3, max_length=120, pattern=r"^[A-Za-z0-9_-]+$")

class OtpVerify(BaseModel):
    session_id: str
    otp: str = Field(min_length=6, max_length=6, pattern=r"^[0-9]{6}$")
