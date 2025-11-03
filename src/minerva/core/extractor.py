"""Embedding extraction using HuggingFace transformers."""

import torch
from transformers import AutoModel, AutoTokenizer


class EmbeddingExtractor:
    """Extract embeddings using HuggingFace transformer models."""

    def __init__(
        self,
        model_name: str = "google/embeddinggemma-300m",
        batch_size: int = 32,
        device: str | None = None,
    ):
        """
        Initialize the embedding extractor.

        Args:
            model_name: HuggingFace model identifier
            batch_size: Default batch size for processing
            device: Device to use ('cuda', 'mps', 'cpu'). Auto-detects if None
        """
        self.model_name: str = model_name
        self.batch_size: int = batch_size
        self.device: str = self._get_device(device)

        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.model = AutoModel.from_pretrained(model_name).to(self.device)
        self.model.eval()

    def _get_device(self, device: str | None) -> str:
        """Detect and return the best available device."""
        if device is not None:
            return device

        if torch.cuda.is_available():
            return "cuda"
        elif torch.backends.mps.is_available():
            return "mps"
        else:
            return "cpu"

    def extract_batch(
        self, texts: list[str], batch_size: int | None = None
    ) -> list[list[float]]:
        """
        Extract embeddings for a batch of texts.

        Args:
            texts: List of texts to extract embeddings for
            batch_size: Batch size for processing. Uses default if None

        Returns:
            List of embedding vectors, one per input text
        """
        if not texts:
            return []

        batch_size = batch_size or self.batch_size
        all_embeddings: list[list[float]] = []

        with torch.no_grad():
            for i in range(0, len(texts), batch_size):
                batch_texts: list[str] = texts[i : i + batch_size]

                inputs = self.tokenizer(
                    batch_texts,
                    padding=True,
                    truncation=True,
                    return_tensors="pt",
                    max_length=512,
                ).to(self.device)

                outputs = self.model(**inputs)
                embeddings: torch.Tensor = outputs.last_hidden_state[:, 0, :]

                batch_embeddings: list[list[float]] = embeddings.cpu().tolist()
                all_embeddings.extend(batch_embeddings)

        return all_embeddings

    def extract_single(self, text: str) -> list[float]:
        """
        Extract embedding for a single text.

        Args:
            text: Text to extract embedding for

        Returns:
            Embedding vector
        """
        return self.extract_batch([text])[0]
