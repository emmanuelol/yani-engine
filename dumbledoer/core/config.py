import os
from pydantic_settings import BaseSettings
from typing import Dict, Any
from dumbledoer.core.llm_provider import AbstractLLMProvider, GeminiProvider, LocalProvider, AntigravityProvider

class AppConfig(BaseSettings):
    # API Keys & Auth
    gemini_api_key: str = None
    google_api_key: str = None
    
    # Execution Settings
    start_at_index: int = 0
    verbose: bool = False
    model: str = "gemini-3.6-flash"
    
    # Budget Defaults
    budget_limit: int = 5000000
    budget_threshold_pct: int = 80
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

    @property
    def providers(self) -> Dict[str, AbstractLLMProvider]:
        """Lazy-loads and returns the configured providers."""
        provs = {}
        # 1. Cloud Provider (The Brain)
        try:
            import agy
            provs["cloud"] = AntigravityProvider()
        except ImportError:
            key = self.gemini_api_key or self.google_api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
            if key:
                provs["cloud"] = GeminiProvider(api_key=key)
                
        # 2. Local Provider (The Hands)
        # Pointing to standard Ollama OpenAI compatibility endpoint
        provs["local"] = LocalProvider(base_url="http://localhost:11434/v1")
        
        if not provs:
            raise RuntimeError("CRITICAL: No LLM providers could be initialized. Check API keys.")
            
        return provs

# Global Singleton instance
config = AppConfig()
