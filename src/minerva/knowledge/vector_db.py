from typing import Callable

from pymilvus import MilvusClient, CollectionSchema


class MilvusVectorDB:
    def __init__(self, db_path: str, collection_name: str):
        self.client = MilvusClient(db_path)
        self.collection_name = collection_name

    def init_collection(self, schema: CollectionSchema, index_params: "IndexParams"):
        if self.client.has_collection(self.collection_name):
            self.client.drop_collection(self.collection_name)

        self.client.create_collection(
            collection_name=self.collection_name,
            schema=schema,
            index_params=index_params
        )

    def add_documents(
        self,
        documents: list[str],
        metadata: list[dict],
        embedding_fn: Callable
    ):
        """Add documents to the vector database."""
        if len(documents) != len(metadata):
            raise ValueError("`add_documents` requires the number of documents "
                             "and metadata to be the same.")

        vectors: list[list[float]] = embedding_fn(documents)
        data = [
            {"vector": vectors[i], **metadata[i]}
            for i in range(len(vectors))
        ]

        self.client.insert(collection_name=self.collection_name, data=data)

    def search(
        self,
        queries: str | list[str],
        embedding_fn: Callable,
        output_fields: list[str],
        filter: str = "",
        limit: int = 10
    ):
        """Search for similar documents in the vector database."""
        if isinstance(queries, str):
            queries = [queries]
        query_vectors = embedding_fn(queries)
        res = self.client.search(
            collection_name=self.collection_name,
            data=query_vectors,
            filter=filter,
            limit=limit,
            output_fields=output_fields
        )
        return res
