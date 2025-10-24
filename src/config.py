from pydantic import BaseSettings

class Settings(BaseSettings):
    bot_token: str
    operators_chat_id: int
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str
    postgres_user: str
    postgres_password: str
    default_region: str = "RU"

    @property
    def dsn(self) -> str:
        return f"postgresql+psycopg2://{self.postgres_user}:{self.postgres_password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"

    class Config:
        env_file = ".env"

settings = Settings()
