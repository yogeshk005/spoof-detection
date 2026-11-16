from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    app_name: str = "BlinkCheck API"
    environment: str = "development"
    mock_mode: bool = True
    database_url: str = "sqlite:///./blinkcheck.db"
    aws_region: str = "us-east-1"
    s3_bucket: str = ""
    cors_origins: str = "http://localhost:5173"
    session_ttl_seconds: int = 180
    otp_secret: str = "change-this-to-a-long-random-secret"
    otp_ttl_seconds: int = 60
    max_scored_attempts: int = 3
    attempt_window_seconds: int = 900
    lockout_seconds: int = 900
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
