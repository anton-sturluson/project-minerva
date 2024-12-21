from openai import OpenAI


class OpenAIClient:
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