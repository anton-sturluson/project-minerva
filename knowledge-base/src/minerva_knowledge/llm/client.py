from abc import ABC, abstractmethod

from anthropic import Anthropic
from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential


class Client(ABC):
    """Base class for LLM clients."""

    @abstractmethod
    def get_completion(
        self,
        prompt: str,
        model: str = "gpt-4o-mini",
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ) -> str:
        """
        Abstract method for getting a completion from an LLM.

        Args:
            prompt (str): The input prompt for the LLM.
            model (str, optional): The model to use. Defaults to "gpt-4o-mini".
            temperature (float, optional): Sampling temperature. Defaults to 0.1.
            max_tokens (int, optional): Maximum number of tokens to generate. Defaults to 4096.

        Returns:
            str: The generated completion.
        """
        raise NotImplementedError

    @staticmethod
    def retry():
        return retry(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=4, max=10),
            reraise=True,
        )


class OpenAIClient(Client):
    """OpenAI client."""

    def __init__(self, api_key: str):
        self.client = OpenAI(api_key=api_key)

    @Client.retry()
    def get_embedding(
        self, texts: str | list[str], model: str = "text-embedding-3-small"
    ) -> list[float]:
        if isinstance(texts, str):
            texts = [texts]
        out = self.client.embeddings.create(input=texts, model=model)
        return [x.embedding for x in out.data]

    @Client.retry()
    def get_completion(
        self,
        prompt: str,
        model: str = "gpt-4o-mini",
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ) -> str:
        out = self.client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return out.choices[0].message.content

    @property
    def batches(self):
        return self.client.batches

    @property
    def files(self):
        return self.client.files


class AnthropicClient(Client):
    """Anthropic client."""

    def __init__(self, api_key: str):
        self.client = Anthropic(api_key=api_key)

    @Client.retry()
    def get_completion(
        self,
        prompt: str,
        model: str = "claude-3-5-sonnet-latest",
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ) -> str:
        out = self.client.messages.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return out.content[0].text
