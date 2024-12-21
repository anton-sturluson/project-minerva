"""Initialize Milvus Vector Database."""
from pymilvus import MilvusClient, DataType

from minerva.util.env import OPENAI_API_KEY
from minerva.llm import OpenAIClient
from minerva.vector_db import MilvusVectorDB


if __name__ == "__main__":
    openai_client = OpenAIClient(api_key=OPENAI_API_KEY)
    embedding_fn = openai_client.get_embedding

    # initialize vector db
    db = MilvusVectorDB(db_path="../data/milvus_demo.db", 
                        collection_name="demo_collection")

    # define schema
    schema = MilvusClient.create_schema(
        auto_id=True,
        enable_dynamic_field=True,
    )
    schema.add_field(field_name="id", datatype=DataType.INT64, is_primary=True)
    schema.add_field(field_name="vector", datatype=DataType.FLOAT_VECTOR, dim=1536)

    # define indexing
    index_params = db.client.prepare_index_params()
    index_params.add_index(
        field_name="vector",
        index_name="vector_index",
        index_type="FLAT",
        metric_type="COSINE"
    )

    db.init_collection(schema=schema, index_params=index_params)

    docs: list[str] = ["Hello World First", "Hello World Second", "Hello World Third"]
    metadata: list[dict] = [{"text": s} for s in docs]
    db.add_documents(
        documents=docs,
        metadata=metadata,
        embedding_fn=embedding_fn
    )
    res = db.search(
        queries="Show me something about second",
        embedding_fn=embedding_fn,
        output_fields=["text"],
        limit=2,
    )
    print(res)