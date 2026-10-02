"""
app/modules/ai_engine/llm_client.py
--------------------------------------
Pluggable LLM client adapter.

Wraps the external LLM provider (e.g. OpenAI) behind a stable interface.
Swap providers by changing LLM_PROVIDER in config without touching generator logic.

Supports structured output via Pydantic models for reliable parsing.
"""

import asyncio
import logging
from typing import Type, TypeVar, Optional
from pydantic import BaseModel

from openai import AsyncOpenAI, APIError, RateLimitError, APITimeoutError
from app.core.config import settings
from app.core.exceptions import ValidationError


logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class LLMClient:
    """
    LLM client with OpenAI support, structured output, retry logic, and error handling.
    Use generate() for raw text or generate_structured() for Pydantic-validated output.
    """

    def __init__(self) -> None:
        self.provider = settings.llm_provider
        self.model = settings.llm_model
        self.api_key = settings.llm_api_key

        # Initialize OpenAI client if provider is openai
        if self.provider == "openai":
            if not self.api_key:
                logger.warning("LLM_API_KEY not set - LLM features will be unavailable")
                self.client: Optional[AsyncOpenAI] = None
            else:
                self.client = AsyncOpenAI(api_key=self.api_key)
        else:
            raise ValueError(f"Unsupported LLM provider: {self.provider}")

    async def generate(
        self,
        prompt: str,
        max_tokens: int = 2000,
        temperature: float = 0.7,
        max_retries: int = 3
    ) -> str:
        """
        Send a prompt to the LLM and return the raw text response.

        Args:
            prompt: The prompt to send
            max_tokens: Maximum tokens in response
            temperature: Sampling temperature (0.0-2.0)
            max_retries: Maximum number of retry attempts on rate limit errors

        Returns:
            Raw text response from the LLM

        Raises:
            ValidationError: If LLM client not initialized or API call fails
        """
        if not self.client:
            raise ValidationError("LLM client not initialized - check LLM_API_KEY configuration")

        for attempt in range(max_retries):
            try:
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "user", "content": prompt}
                    ],
                    max_tokens=max_tokens,
                    temperature=temperature,
                    timeout=60.0
                )

                content = response.choices[0].message.content
                if not content:
                    raise ValidationError("LLM returned empty response")

                return content

            except RateLimitError as e:
                if attempt < max_retries - 1:
                    # Exponential backoff: 2^attempt seconds
                    wait_time = 2 ** attempt
                    logger.warning(f"Rate limit hit, retrying in {wait_time}s (attempt {attempt + 1}/{max_retries})")
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"Rate limit exceeded after {max_retries} attempts")
                    raise ValidationError(f"LLM rate limit exceeded: {str(e)}")

            except APITimeoutError as e:
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    logger.warning(f"API timeout, retrying in {wait_time}s (attempt {attempt + 1}/{max_retries})")
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"API timeout after {max_retries} attempts")
                    raise ValidationError(f"LLM timeout: {str(e)}")

            except APIError as e:
                logger.error(f"LLM API error: {str(e)}")
                raise ValidationError(f"LLM API error: {str(e)}")

            except Exception as e:
                logger.error(f"Unexpected LLM error: {str(e)}")
                raise ValidationError(f"LLM error: {str(e)}")

        raise ValidationError("LLM request failed after all retries")

    async def generate_structured(
        self,
        prompt: str,
        response_model: Type[T],
        max_tokens: int = 4000,
        temperature: float = 0.3,
        max_retries: int = 3
    ) -> T:
        """
        Send a prompt to the LLM and return a structured Pydantic model response.

        Args:
            prompt: The prompt to send
            response_model: Pydantic model class for structured output
            max_tokens: Maximum tokens in response
            temperature: Sampling temperature (lower for more structured output)
            max_retries: Maximum number of retry attempts

        Returns:
            Instance of response_model with validated LLM output

        Raises:
            ValidationError: If LLM client not initialized, API call fails, or output invalid
        """
        if not self.client:
            raise ValidationError("LLM client not initialized - check LLM_API_KEY configuration")

        for attempt in range(max_retries):
            try:
                # Use OpenAI's structured output feature with response_format
                response = await self.client.beta.chat.completions.parse(
                    model=self.model,
                    messages=[
                        {"role": "user", "content": prompt}
                    ],
                    response_format=response_model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    timeout=60.0
                )

                parsed = response.choices[0].message.parsed
                if not parsed:
                    raise ValidationError("LLM returned empty structured response")

                # Validate against Pydantic model
                validated = response_model.model_validate(parsed.model_dump())
                return validated

            except RateLimitError as e:
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    logger.warning(f"Rate limit hit, retrying in {wait_time}s (attempt {attempt + 1}/{max_retries})")
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"Rate limit exceeded after {max_retries} attempts")
                    raise ValidationError(f"LLM rate limit exceeded: {str(e)}")

            except APITimeoutError as e:
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    logger.warning(f"API timeout, retrying in {wait_time}s (attempt {attempt + 1}/{max_retries})")
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"API timeout after {max_retries} attempts")
                    raise ValidationError(f"LLM timeout: {str(e)}")

            except APIError as e:
                logger.error(f"LLM API error: {str(e)}")
                raise ValidationError(f"LLM API error: {str(e)}")

            except Exception as e:
                logger.error(f"Unexpected LLM error or validation failure: {str(e)}")
                raise ValidationError(f"LLM error: {str(e)}")

        raise ValidationError("LLM structured request failed after all retries")


# Module-level singleton — import this instead of instantiating directly.
llm_client = LLMClient()
