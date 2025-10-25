from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    bot_token: str
    operators_chat_id: int
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str
    postgres_user: str
    postgres_password: str
    default_region: str = "RU"
    media_root: str = "media"
    store_media_local: bool = True 


    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8')

    @property
    def dsn(self) -> str:
        return f"postgresql+psycopg2://{self.postgres_user}:{self.postgres_password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"

settings = Settings()
