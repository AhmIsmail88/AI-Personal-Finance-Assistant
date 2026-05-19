from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv

load_dotenv()

class Settings(BaseSettings):
    telegram_token: str
    postgres_url: str

    # API Keys — only GROQ_API_KEY is needed (free, fast, reliable)
    groq_api_key: str
    openai_api_key: str | None = None      # optional fallback
    openrouter_api_key: str | None = None  # optional fallback

    # URLs
    webhook_url: str
    groq_base_url: str = "https://api.groq.com/openai/v1"

    # Groq models — all support json_mode, no rate-limit pressure
    router_model: str    = "llama-3.3-70b-versatile"
    extractor_model: str = "llama-3.3-70b-versatile"
    analyst_model: str   = "llama-3.3-70b-versatile"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
