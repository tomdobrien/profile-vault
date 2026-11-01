from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    app_env: str = "development"
    database_url: str = "sqlite:///./data/profile.db"
    published_resume_path: str = "./data/published-resume.json"
    frontend_origin: str = "http://localhost:3000"
    admin_password: str | None = None
    admin_session_secret: str | None = None
    photo_upload_dir: str = "./data/photos"
    photo_upload_mount: str | None = None
    model_config = SettingsConfigDict(env_file=(".env", "backend/.env"), extra="ignore")

    @property
    def sqlalchemy_database_url(self) -> str:
        # psycopg 3 is installed; normalize the common PostgreSQL URL form to its driver.
        if self.database_url.startswith("postgresql://"):
            return self.database_url.replace("postgresql://", "postgresql+psycopg://", 1)
        return self.database_url

    @property
    def allowed_frontend_origins(self) -> list[str]:
        return [origin.strip().rstrip("/") for origin in self.frontend_origin.split(",") if origin.strip()]

settings = Settings()
