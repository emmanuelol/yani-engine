import os
from pydantic_settings import BaseSettings
from typing import Dict, Any
from yani_engine.core.llm_provider import AbstractLLMProvider, GeminiProvider, LocalProvider, AntigravityProvider
import socket

def _is_local_alive(port=11434):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.2)
        return s.connect_ex(('127.0.0.1', port)) == 0

# [FIX]: Global cache to prevent leaking httpx connections on repeated property access
_GLOBAL_PROVIDER_CACHE = None

class AppConfig(BaseSettings):
    # API Keys & Auth
    gemini_api_key: str | None = None
    google_api_key: str | None = None
    
    # Execution Settings
    start_at_index: int = 1
    verbose: bool = False
    
    # Vendor-Agnostic Model Tiers
    model_fast: str = "gemini-3.6-flash"
    model_heavy: str = "gemini-3.1-pro-preview"
    
    # Budget Defaults
    budget_limit: int = 50000000
    budget_threshold_pct: int = 80
    
    class Config:
        env_file = (os.path.expanduser("~/.gemini/config/plugins/yani-engine/.env"), ".env")
        env_file_encoding = "utf-8"
        extra = "ignore"

    @property
    def providers(self) -> Dict[str, AbstractLLMProvider]:
        global _GLOBAL_PROVIDER_CACHE
        if _GLOBAL_PROVIDER_CACHE is not None:
            return _GLOBAL_PROVIDER_CACHE

        provs = {}
        try:
            import agy
            provs["cloud"] = AntigravityProvider()
        except (ImportError, RuntimeError): # [FIX]: Catch RuntimeError if native agy modules are broken
            key = self.gemini_api_key or self.google_api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
            if key:
                provs["cloud"] = GeminiProvider(api_key=key)
                
        if _is_local_alive():
            provs["local"] = LocalProvider(base_url="http://localhost:11434/v1")
            
        if not provs:
            raise RuntimeError("CRITICAL: No LLM providers could be initialized. Check API keys.")
            
        _GLOBAL_PROVIDER_CACHE = provs
        return provs

# Global Singleton instance
config = AppConfig()
