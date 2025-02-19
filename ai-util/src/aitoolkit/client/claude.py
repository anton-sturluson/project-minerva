"""Claude client."""
from anthropic import Anthropic
#     AsyncAnthropic,
#     RateLimitError,
#     BadRequestError
# )

from langchain_anthropic import ChatAnthropic
from pydantic import BaseModel

from .base import BaseClient

# NO_RETRY_ERRORS: tuple[str] = (BadRequestError, ValueError, KeyError, TypeError)

class ClaudeClient(BaseClient):
    """Claude client with langchain backend."""
    def __init__(
        self,
        model: str,
        api_key: str,
        schema: BaseModel | None = None,
        set_retry: bool = True,
        **kwargs
    ):
        super().__init__(model, api_key)
        self.llm = ChatAnthropic(
            model=model,
            api_key=api_key,
            **kwargs
        )
        self.init_llm(schema, set_retry)

    @property
    def original_client(self):
        if self._original_client is None:
            self._original_client = Anthropic(api_key=self.api_key)
        return self._original_client

    @property
    def messages(self):
        return self.original_client.messages
