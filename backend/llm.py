"""
LLM Interface — Unified interface for Gemini Flash API and Ollama (local).

Supports two providers:
  - "gemini": Google Gemini Flash API (free tier: ~1500 req/day)
  - "ollama": Local Ollama with any model (completely free, needs local setup)

Both share the same interface: llm.generate(prompt) → response text
"""

import os
from abc import ABC, abstractmethod

from dotenv import load_dotenv

load_dotenv()


class BaseLLM(ABC):
    """Abstract base class for LLM providers."""

    @abstractmethod
    def generate(self, prompt, system_prompt=None, temperature=0.3, max_tokens=1500):
        """
        Generate a response from the LLM.

        Args:
            prompt: The user prompt / question with context
            system_prompt: Optional system instruction
            temperature: Creativity (0 = deterministic, 1 = creative)
            max_tokens: Maximum response length

        Returns:
            str: The generated response text
        """
        pass

    @abstractmethod
    def is_available(self):
        """Check if this provider is configured and reachable."""
        pass


class GeminiLLM(BaseLLM):
    """Google Gemini Flash API — free tier."""

    def __init__(self, api_key=None, model=None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY", "")
        self.model_name = model or os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
        self._client = None

    def _get_client(self):
        """Lazy-initialize the Gemini client."""
        if self._client is None:
            from google import genai
            self._client = genai.Client(api_key=self.api_key)
        return self._client

    def generate(self, prompt, system_prompt=None, temperature=0.3, max_tokens=1500):
        """Generate using Gemini API."""
        from google.genai import types

        client = self._get_client()

        config = types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
        )
        if system_prompt:
            config.system_instruction = system_prompt

        response = client.models.generate_content(
            model=self.model_name,
            contents=prompt,
            config=config,
        )

        return response.text

    def is_available(self):
        """Check if Gemini API key is configured."""
        if not self.api_key or self.api_key == "your_gemini_api_key_here":
            return False
        try:
            # Quick test with minimal tokens
            self.generate("Say 'ok'", max_tokens=10)
            return True
        except Exception as e:
            print(f"Gemini not available: {e}")
            return False


class OllamaLLM(BaseLLM):
    """Local Ollama — completely free, runs on your machine."""

    def __init__(self, base_url=None, model=None):
        self.base_url = base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        self.model_name = model or os.getenv("OLLAMA_MODEL", "gemma3:4b")

    def generate(self, prompt, system_prompt=None, temperature=0.3, max_tokens=1500):
        """Generate using local Ollama."""
        import httpx

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        response = httpx.post(
            f"{self.base_url}/api/chat",
            json={
                "model": self.model_name,
                "messages": messages,
                "stream": False,
                "options": {
                    "temperature": temperature,
                    "num_predict": max_tokens,
                },
            },
            timeout=120.0,
        )
        response.raise_for_status()
        data = response.json()
        return data.get("message", {}).get("content", "")

    def is_available(self):
        """Check if Ollama is running locally."""
        try:
            import httpx
            resp = httpx.get(f"{self.base_url}/api/tags", timeout=5.0)
            return resp.status_code == 200
        except Exception:
            return False


def get_llm(provider=None):
    """
    Factory function to get the configured LLM provider.

    Tries the configured provider first, then falls back to the other.

    Args:
        provider: "gemini" or "ollama" (or None for auto-detect)

    Returns:
        BaseLLM instance
    """
    provider = provider or os.getenv("LLM_PROVIDER", "gemini")

    if provider == "gemini":
        llm = GeminiLLM()
        if llm.is_available():
            print(f"Using Gemini API ({llm.model_name})")
            return llm
        print("Gemini not available, trying Ollama fallback...")
        llm = OllamaLLM()
        if llm.is_available():
            print(f"Using Ollama ({llm.model_name})")
            return llm
    elif provider == "ollama":
        llm = OllamaLLM()
        if llm.is_available():
            print(f"Using Ollama ({llm.model_name})")
            return llm
        print("Ollama not available, trying Gemini fallback...")
        llm = GeminiLLM()
        if llm.is_available():
            print(f"Using Gemini API ({llm.model_name})")
            return llm

    raise RuntimeError(
        "No LLM provider available!\n"
        "  Option A: Set GEMINI_API_KEY in .env (free from https://aistudio.google.com/apikey)\n"
        "  Option B: Install Ollama (https://ollama.com) and run: ollama pull gemma3:4b"
    )


if __name__ == "__main__":
    llm = get_llm()
    response = llm.generate(
        "What is UNSW? Answer in one sentence.",
        temperature=0.1,
    )
    print(f"\nResponse: {response}")
