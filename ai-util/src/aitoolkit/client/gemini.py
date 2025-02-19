"""Gemini client."""
# from google.genai import errors

from langchain_google_genai.chat_models import ChatGoogleGenerativeAI
from pydantic import BaseModel

from .base import BaseClient

# NO_RETRY_ERRORS: tuple[str] = (
#     errors.UnsupportedFunctionError, errors.FunctionInvocationError,
#     errors.UnknownFunctionCallArgumentError, ValueError, KeyError, TypeError)

class GeminiClient(BaseClient):
    """Gemini client with langchain backend."""
    def __init__(
        self,
        model: str,
        api_key: str,
        schema: BaseModel | None = None,
        set_retry: bool = True,
        **kwargs
    ):
        super().__init__(model, api_key)
        self.llm = ChatGoogleGenerativeAI(
            model=model,
            google_api_key=api_key,
            **kwargs
        )
        self.init_llm(schema, set_retry)
