"""Base client class for LLM providers."""
from abc import ABC

from langsmith import traceable
from pydantic import BaseModel

class BaseClient(ABC):
    """Base class for LLM providers."""
    def __init__(self, model: str, api_key: str):
        self.llm = None
        self.model: str = model
        self.api_key: str = api_key
        self._original_client = None
        self.has_schema: bool = False

    def init_llm(
        self,
        schema: BaseModel | None = None,
        set_retry: bool = True,
        **kwargs
    ):
        """Initialize the LLM."""
        if self.llm is None:
            raise ValueError("LLM not initialized")
        if schema:
            self.has_schema = True
            self.set_schema(schema)
        if set_retry:
            self.set_retry()

    def set_retry(
        self,
        stop_after_attempt: int = 5,
        wait_exponential_jitter: bool = True,
        retry_if_exception_type: tuple[str | Exception] = (Exception,)
    ):
        """Initialize the LLM wtih built-in retry logic."""
        if self.llm is None:
            raise ValueError("LLM not initialized")
        self.llm = self.llm.with_retry(
            stop_after_attempt=stop_after_attempt,
            wait_exponential_jitter=wait_exponential_jitter,
            retry_if_exception_type=retry_if_exception_type
        )

    def set_schema(self, schema: BaseModel):
        """Return a new client with structured output."""
        if self.llm is None:
            raise ValueError("LLM not initialized")
        self.llm = self.llm.with_structured_output(schema)

    @traceable
    def invoke(self, prompt: str) -> BaseModel:
        """Invoke the LLM."""
        return self.llm.invoke(prompt)

    @traceable
    def ainvoke(self, prompt: str) -> BaseModel:
        """Invoke the LLM asynchronously."""
        return self.llm.ainvoke(prompt)
