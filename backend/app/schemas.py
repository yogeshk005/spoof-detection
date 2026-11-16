from pydantic import BaseModel, Field

class EnrollStart(BaseModel):
    credential_id: str = Field(min_length=3, max_length=120, pattern=r"^[A-Za-z0-9_-]+$")
    display_name: str = Field(min_length=2, max_length=120)

class VerifyStart(BaseModel):
    credential_id: str = Field(min_length=3, max_length=120, pattern=r"^[A-Za-z0-9_-]+$")

class OtpVerify(BaseModel):
    session_id: str
    otp: str = Field(min_length=6, max_length=6, pattern=r"^[0-9]{6}$")
