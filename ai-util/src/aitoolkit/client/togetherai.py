"""TogetherAI client."""
# from together import error

from langchain_together import ChatTogether
from pydantic import BaseModel

from client.base import BaseClient

# NO_RETRY_ERRORS: tuple[str] = (
#     error.InvalidRequestError, error.AttributeError,
#     ValueError, KeyError, TypeError)

class TogetherAIClient(BaseClient):
    """TogetherAI client with both sync and async capabilities."""
    def __init__(
        self,
        model: str,
        api_key: str,
        schema: BaseModel | None = None,
        set_retry: bool = True,
        **kwargs
    ):
        super().__init__(model, api_key)
        self.llm = ChatTogether(
            model=model,
            api_key=api_key,
            **kwargs
        )
        self.init_llm(schema, set_retry)
