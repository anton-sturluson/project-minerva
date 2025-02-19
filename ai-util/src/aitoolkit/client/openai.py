"""OpenAI client."""
# from openai import BadRequestError, AuthenticationError, PermissionDeniedError

from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from .base import BaseClient

# NO_RETRY_ERRORS: tuple[str] = (
#     BadRequestError, AuthenticationError, PermissionDeniedError,
#     ValueError, KeyError, TypeError)

class OpenAIClient(BaseClient):
    """OpenAI client with langchain backend."""
    def __init__(
        self,
        model: str,
        api_key: str,
        schema: BaseModel | None = None,
        set_retry: bool = True,
        **kwargs
    ):
        super().__init__(model, api_key)
        self.llm = ChatOpenAI(
            model=model,
            api_key=api_key,
            **kwargs
        )
        self.init_llm(schema, set_retry)
