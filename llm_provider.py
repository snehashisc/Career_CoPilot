"""
LLM Provider Abstraction Layer

This module provides a unified interface for different LLM providers (Claude, Gemini, OpenAI, etc.)
Making it easy to switch between providers with minimal code changes.
"""

from __future__ import annotations

import os
import json
from abc import ABC, abstractmethod
from typing import Any, Optional
from dataclasses import dataclass


@dataclass
class LLMResponse:
    """Unified response format from any LLM provider"""
    content: str
    model: str
    tokens_used: Optional[int] = None
    cost_estimate: Optional[float] = None


class LLMProvider(ABC):
    """Abstract base class for LLM providers"""
    
    @abstractmethod
    def generate(
        self,
        prompt: str,
        max_tokens: int = 2000,
        temperature: float = 0.3,
        system_prompt: Optional[str] = None,
    ) -> LLMResponse:
        """Generate a response from the LLM"""
        pass
    
    @abstractmethod
    def is_available(self) -> bool:
        """Check if the provider is configured and available"""
        pass
    
    @abstractmethod
    def get_provider_name(self) -> str:
        """Get the provider name"""
        pass


class ClaudeProvider(LLMProvider):
    """Anthropic Claude provider"""
    
    def __init__(self, api_key: Optional[str] = None, model: str = "claude-3-5-sonnet-20241022"):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self.model = model
        self._client = None
    
    def _get_client(self):
        if not self._client and self.api_key:
            from anthropic import Anthropic
            self._client = Anthropic(api_key=self.api_key)
        return self._client
    
    def is_available(self) -> bool:
        return bool(self.api_key and self.api_key.startswith("sk-ant-"))
    
    def get_provider_name(self) -> str:
        return "Claude (Anthropic)"
    
    def generate(
        self,
        prompt: str,
        max_tokens: int = 2000,
        temperature: float = 0.3,
        system_prompt: Optional[str] = None,
    ) -> LLMResponse:
        client = self._get_client()
        if not client:
            raise ValueError("Claude API key not configured")
        
        messages = [{"role": "user", "content": prompt}]
        
        response = client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=messages,
        )
        
        text_chunks = []
        for block in response.content:
            if hasattr(block, "text"):
                text_chunks.append(block.text)
        
        content = "\n".join(text_chunks)
        
        # Estimate cost (approximate)
        input_tokens = len(prompt.split()) * 1.3
        output_tokens = len(content.split()) * 1.3
        cost = (input_tokens * 0.003 / 1000) + (output_tokens * 0.015 / 1000)
        
        return LLMResponse(
            content=content,
            model=self.model,
            tokens_used=int(input_tokens + output_tokens),
            cost_estimate=cost,
        )


class GeminiProvider(LLMProvider):
    """Google Gemini provider"""
    
    def __init__(self, api_key: Optional[str] = None, model: str = "models/gemini-2.5-flash"):
        self.api_key = api_key or os.getenv("GOOGLE_API_KEY")
        self.model = model
        self._client = None
    
    def _get_client(self):
        if not self._client and self.api_key:
            from google import genai
            self._client = genai.Client(api_key=self.api_key)
        return self._client
    
    def is_available(self) -> bool:
        return bool(self.api_key)
    
    def get_provider_name(self) -> str:
        return "Gemini (Google)"
    
    def generate(
        self,
        prompt: str,
        max_tokens: int = 2000,
        temperature: float = 0.3,
        system_prompt: Optional[str] = None,
    ) -> LLMResponse:
        client = self._get_client()
        if not client:
            raise ValueError("Gemini API key not configured")
        
        full_prompt = prompt
        if system_prompt:
            full_prompt = f"{system_prompt}\n\n{prompt}"
        
        # Use the correct API format for google-genai
        response = client.models.generate_content(
            model=self.model,
            contents=full_prompt,
            config={
                "max_output_tokens": max_tokens,
                "temperature": temperature,
                "response_mime_type": "text/plain",
            }
        )
        
        # Extract text from response
        content = response.text if hasattr(response, 'text') else str(response)
        
        # Estimate cost (Gemini pricing)
        input_tokens = len(prompt.split()) * 1.3
        output_tokens = len(content.split()) * 1.3
        cost = (input_tokens * 0.00035 / 1000) + (output_tokens * 0.00105 / 1000)
        
        return LLMResponse(
            content=content,
            model=self.model,
            tokens_used=int(input_tokens + output_tokens),
            cost_estimate=cost,
        )


class OpenAIProvider(LLMProvider):
    """OpenAI GPT provider"""
    
    def __init__(self, api_key: Optional[str] = None, model: str = "gpt-4o"):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.model = model
        self._client = None
    
    def _get_client(self):
        if not self._client and self.api_key:
            from openai import OpenAI
            self._client = OpenAI(api_key=self.api_key)
        return self._client
    
    def is_available(self) -> bool:
        return bool(self.api_key and self.api_key.startswith("sk-"))
    
    def get_provider_name(self) -> str:
        return "GPT (OpenAI)"
    
    def generate(
        self,
        prompt: str,
        max_tokens: int = 2000,
        temperature: float = 0.3,
        system_prompt: Optional[str] = None,
    ) -> LLMResponse:
        client = self._get_client()
        if not client:
            raise ValueError("OpenAI API key not configured")
        
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        
        response = client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        
        content = response.choices[0].message.content or ""
        
        # Actual token usage from API
        tokens_used = response.usage.total_tokens if response.usage else 0
        
        # Estimate cost (GPT-4o pricing)
        input_tokens = response.usage.prompt_tokens if response.usage else 0
        output_tokens = response.usage.completion_tokens if response.usage else 0
        cost = (input_tokens * 0.005 / 1000) + (output_tokens * 0.015 / 1000)
        
        return LLMResponse(
            content=content,
            model=self.model,
            tokens_used=tokens_used,
            cost_estimate=cost,
        )


class LLMFactory:
    """Factory to create and manage LLM providers"""
    
    _instance: Optional[LLMProvider] = None
    _provider_type: Optional[str] = None
    
    @classmethod
    def get_provider(cls, provider_type: Optional[str] = None) -> Optional[LLMProvider]:
        """
        Get LLM provider instance.
        
        Args:
            provider_type: "claude", "gemini", "openai", or None (auto-detect)
        
        Returns:
            LLMProvider instance or None if no provider is available
        """
        # If provider type changed, reset instance
        if provider_type and provider_type != cls._provider_type:
            cls._instance = None
            cls._provider_type = provider_type
        
        # Return cached instance if available
        if cls._instance:
            return cls._instance
        
        # Auto-detect provider if not specified
        if not provider_type:
            provider_type = os.getenv("LLM_PROVIDER", "claude").lower()
        
        # Try to create provider
        providers = {
            "claude": ClaudeProvider,
            "gemini": GeminiProvider,
            "openai": OpenAIProvider,
        }
        
        provider_class = providers.get(provider_type)
        if not provider_class:
            print(f"[WARNING] Unknown provider type: {provider_type}")
            return None
        
        try:
            provider = provider_class()
            if provider.is_available():
                cls._instance = provider
                cls._provider_type = provider_type
                print(f"[INFO] LLM Provider initialized: {provider.get_provider_name()}")
                return provider
            else:
                print(f"[INFO] {provider.get_provider_name()} not available (API key not configured)")
        except Exception as e:
            print(f"[ERROR] Failed to initialize {provider_type} provider: {e}")
        
        return None
    
    @classmethod
    def reset(cls):
        """Reset the provider instance (useful for testing)"""
        cls._instance = None
        cls._provider_type = None


def generate_with_llm(
    prompt: str,
    max_tokens: int = 2000,
    temperature: float = 0.3,
    system_prompt: Optional[str] = None,
    provider_type: Optional[str] = None,
) -> Optional[str]:
    """
    Convenience function to generate text using the configured LLM provider.
    
    Args:
        prompt: The prompt to send to the LLM
        max_tokens: Maximum tokens to generate
        temperature: Sampling temperature (0.0 - 1.0)
        system_prompt: Optional system prompt
        provider_type: Optional provider override ("claude", "gemini", "openai")
    
    Returns:
        Generated text or None if no provider available
    """
    provider = LLMFactory.get_provider(provider_type)
    if not provider:
        return None
    
    try:
        response = provider.generate(
            prompt=prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            system_prompt=system_prompt,
        )
        return response.content
    except Exception as e:
        print(f"[ERROR] LLM generation failed: {e}")
        return None


def extract_json_from_llm_response(text: str) -> Optional[dict[str, Any]]:
    """Extract JSON object from LLM response text"""
    text = text.strip()
    
    # Try direct parse
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    
    # Try to find JSON object in text
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        snippet = text[start : end + 1]
        try:
            parsed = json.loads(snippet)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
    
    return None
