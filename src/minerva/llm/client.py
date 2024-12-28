from openai import OpenAI


class Client:
    """Base class for LLM clients."""
    pass


class OpenAIClient(Client):
    """OpenAI client."""
    def __init__(self, api_key: str):
        self.client = OpenAI(api_key=api_key)

    def get_embedding(
        self,
        texts: str | list[str],
        model: str = "text-embedding-3-small"
    ) -> list[float]:
        if isinstance(texts, str):
            texts = [texts]
        out = self.client.embeddings.create(input=texts, model=model)
        return [x.embedding for x in out.data]

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
