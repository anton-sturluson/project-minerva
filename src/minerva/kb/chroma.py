"""Chroma vector database client for the Knowledge Base."""

from typing import Any

import chromadb
from chromadb.api.models.Collection import Collection
from chromadb.config import Settings

from .model import VectorDocument, QueryResult
from .utils import chunk_text


class ChromaKB:
    """Chroma client for managing vector embeddings of knowledge base sections."""

    def __init__(
        self, path: str = "./.chroma_db", collection_name: str = "knowledge_base"
    ) -> None:
        self.client: chromadb.PersistentClient = chromadb.PersistentClient(
            path=path, settings=Settings(anonymized_telemetry=False)
        )
        self.collection: Collection = self.client.get_or_create_collection(
            name=collection_name
        )

    def add(
        self,
        section_id: str,
        content: str,
        metadata: dict[str, Any] | None = None,
        chunk_size: int = 500,
    ) -> bool:
        """Add a section's content to the vector database."""
        chunks: list[str] = chunk_text(content, chunk_size=chunk_size)
        metadata = metadata or {}

        ids: list[str] = []
        documents: list[str] = []
        metadatas: list[dict[str, Any]] = []

        for i, chunk in enumerate(chunks):
            chunk_id: str = f"{section_id}_{i}" if len(chunks) > 1 else section_id
            ids.append(chunk_id)
            documents.append(chunk)
            metadatas.append({**metadata, "chunk_index": i, "section_id": section_id})

        self.collection.add(ids=ids, documents=documents, metadatas=metadatas)
        return True

    def get(self, section_id: str) -> list[VectorDocument]:
        """Get all chunks for a section."""
        results: dict[str, Any] = self.collection.get(where={"section_id": section_id})

        if not results or not results["ids"]:
            return []

        documents: list[VectorDocument] = []
        for i, doc_id in enumerate(results["ids"]):
            documents.append(
                VectorDocument(
                    document_id=doc_id,
                    section_id=section_id,
                    chunk_index=results["metadatas"][i].get("chunk_index", 0),
                    content=results["documents"][i],
                    metadata=results["metadatas"][i],
                )
            )

        return sorted(documents, key=lambda x: x.chunk_index)

    def delete(self, section_id: str) -> bool:
        """Delete all chunks for a section."""
        try:
            # Get all document IDs for this section
            results: dict[str, Any] = self.collection.get(
                where={"section_id": section_id}
            )
            if results and results["ids"]:
                self.collection.delete(ids=results["ids"])
            return True
        except Exception:
            return False

    def search(
        self,
        query: str,
        n_results: int = 5,
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[QueryResult]:
        """Search for similar content using text query."""
        results: dict[str, Any] = self.collection.query(
            query_texts=[query],
            n_results=n_results,
            where=metadata_filter,
        )

        if not results or not results["ids"] or not results["ids"][0]:
            return []

        query_results: list[QueryResult] = []
        for i in range(len(results["ids"][0])):
            query_results.append(
                QueryResult(
                    section_id=results["metadatas"][0][i]["section_id"],
                    header=results["metadatas"][0][i].get("header", ""),
                    content=results["documents"][0][i],
                    similarity=1 - results["distances"][0][i],
                    metadata=results["metadatas"][0][i],
                )
            )

        return query_results

    def search_by_embedding(
        self,
        embedding: list[float],
        n_results: int = 5,
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[QueryResult]:
        """Search for similar content using embedding vector."""
        results: dict[str, Any] = self.collection.query(
            query_embeddings=[embedding],
            n_results=n_results,
            where=metadata_filter,
        )

        if not results or not results["ids"] or not results["ids"][0]:
            return []

        query_results: list[QueryResult] = []
        for i in range(len(results["ids"][0])):
            query_results.append(
                QueryResult(
                    section_id=results["metadatas"][0][i]["section_id"],
                    header=results["metadatas"][0][i].get("header", ""),
                    content=results["documents"][0][i],
                    similarity=1 - results["distances"][0][i],
                    metadata=results["metadatas"][0][i],
                )
            )

        return query_results

    def update(
        self, section_id: str, content: str, metadata: dict[str, Any] | None = None
    ) -> bool:
        """Update a section's content in the vector database."""
        self.delete(section_id)
        return self.add(section_id, content, metadata)

    def clear(self) -> None:
        """Clear all documents from the collection."""
        self.client.delete_collection(self.collection.name)
        self.collection = self.client.get_or_create_collection(
            name=self.collection.name,
            configuration={
                "hnsw": {
                    "space": "cosine",
                    "ef_construction": 200
                }
            }
        )
