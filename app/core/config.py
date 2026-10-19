"""
Centralized configuration for the Smart Building Enterprise Platform.
Uses Pydantic BaseSettings for environment variable management.
"""
import os
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # ── Application ──────────────────────────────────────────────────────
    APP_NAME: str = "Smart Building Enterprise Platform"
    APP_VERSION: str = "2.0.0"
    DEBUG: bool = False
    API_PREFIX: str = ""

    # ── Server ───────────────────────────────────────────────────────────
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # ── Database ─────────────────────────────────────────────────────────
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "admin"
    POSTGRES_PASSWORD: str = "adminpassword"
    POSTGRES_DB: str = "smartbuilding"

    # ── Redis ────────────────────────────────────────────────────────────
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379

    # ── MQTT ─────────────────────────────────────────────────────────────
    MQTT_BROKER: str = "localhost"
    MQTT_PORT: int = 1883
    MQTT_TOPIC_SENSORS: str = "smartbuilding/sensors/#"
    MQTT_TOPIC_ACTUATORS: str = "smartbuilding/actuators"

    # ── AI / ML ──────────────────────────────────────────────────────────
    OCCUPANCY_MODEL_PATH: str = "models/final_unified_occupancy_pipeline.pkl"
    PPO_MODEL_PATH: str = "models/ppo_building_controller.zip"
    OCCUPANCY_THRESHOLD: float = 0.20
    GEMINI_API_KEY: Optional[str] = None

    # ── WSO2 ─────────────────────────────────────────────────────────────
    WSO2_AM_URL: str = "https://localhost:8243"
    WSO2_MI_URL: str = "http://localhost:8290"
    WSO2_IS_URL: str = "https://localhost:9443"

    # ── JWT Auth (Demo Mode) ─────────────────────────────────────────────
    JWT_SECRET_KEY: str = "smart-building-secret-key-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRATION_MINUTES: int = 60

    # ── Project Paths ────────────────────────────────────────────────────
    PROJECT_ROOT: str = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    CONFIG_YAML_PATH: str = "config.yaml"
    KNOWLEDGE_DOCS_PATH: str = "docs/knowledge"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


# Singleton instance
settings = Settings()
