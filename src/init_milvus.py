"""Initialize Milvus Vector Database."""
import logging
from typing import Callable

import click
from pymilvus import MilvusClient, DataType
from tqdm import tqdm

from minerva.knowledge.kb import CompanyKB
from minerva.knowledge.vector_db import MilvusVectorDB
from minerva.llm import useful as llm
from minerva.llm.client import OpenAIClient
from minerva.util.env import OPENAI_API_KEY
from minerva.util.file import File


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)
DEFAULT_DB_PATH: str = "../data/milvus_demo.db"
DEFAULT_COLLECTION_NAME: str = "demo_collection"


def init_milvus(
    db_path: str = DEFAULT_DB_PATH, 
    collection_name: str = DEFAULT_COLLECTION_NAME
) -> MilvusVectorDB:
    """Initialize Milvus Vector Database."""
    # initialize vector db
    db = MilvusVectorDB(db_path=db_path, collection_name=collection_name)

    # define schema
    schema = MilvusClient.create_schema(
        auto_id=True,
        enable_dynamic_field=True,
    )
    schema.add_field(field_name="id", datatype=DataType.INT64, is_primary=True, auto_id=True)
    schema.add_field(field_name="ticker", datatype=DataType.VARCHAR, max_length=4)
    schema.add_field(field_name="company_name", datatype=DataType.VARCHAR, max_length=128)
    schema.add_field(field_name="text", datatype=DataType.VARCHAR, max_length=2048)
    schema.add_field(field_name="speaker", datatype=DataType.VARCHAR, max_length=50)
    schema.add_field(field_name="year", datatype=DataType.INT64)
    schema.add_field(field_name="quarter", datatype=DataType.INT64)
    schema.add_field(field_name="transcript_index", datatype=DataType.INT64)
    schema.add_field(field_name="chunk_index", datatype=DataType.INT64)
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
    return db


def add_documents(
    db: MilvusVectorDB, 
    embedding_fn: Callable,
    ticker: str
):
    """Add documents in the KB to Milvus Vector Database."""
    kb = CompanyKB()
    for company_map in tqdm(kb.transcripts.find({"ticker": ticker}), desc="Adding documents"):
        for transcript_maps in tqdm(company_map["transcripts"], desc="Adding transcripts"):
            year: int = transcript_maps["year"]
            quarter: int = transcript_maps["quarter"]

            # transcript_map: dict[str, int | str]
            docs: list[str] = []
            metadata: list[dict] = []
            for transcript_map in transcript_maps["transcript"]:
                text: str = transcript_map["text"]
                speaker: str = transcript_map["speaker"]
                transcript_index: int = transcript_map["index"]
                # chunk: str
                for i, chunk in enumerate(transcript_map["chunks"]):
                    docs.append(chunk)
                    metadata.append({
                        "text": chunk,
                        "ticker": ticker,
                        "company_name": company_map["company_name"],
                        "speaker": speaker,
                        "year": year,
                        "quarter": quarter,
                        "transcript_index": transcript_index,
                        "chunk_index": i
                    })

            db.add_documents(
                documents=docs,
                metadata=metadata,
                embedding_fn=embedding_fn
            )


@click.command()
@click.option(
    "--query", type=str, default="", 
    help="Query to search for in the vector database")
@click.option(
    "--tickers", type=str, default="AVGO", 
    help="Ticker of the companies (separated by comma) to include")
@click.option(
    "--db-path", type=str, default="../data/milvus_demo.db", 
    help=("Path to the Milvus Vector Database. If not provided, a new database "
          "will be created.  "))
@click.option(
    "--query-save-dir", type=str, default="../data/query_results", 
    help="Directory to save query results")
def main(query: str, tickers: str, db_path: str, query_save_dir: str):
    if not query:
        raise ValueError("Query is required")

    openai_client = OpenAIClient(api_key=OPENAI_API_KEY)
    embedding_fn: Callable = openai_client.get_embedding

    if File(db_path).exists:
        logger.info("Loading Milvus Vector DB from %s...", db_path)
        db: MilvusVectorDB = MilvusVectorDB(
            db_path=db_path, collection_name=DEFAULT_COLLECTION_NAME)
    else:
        if not db_path:
            db_path = DEFAULT_DB_PATH
        logger.info("Initializing Milvus Vector Database...")
        db: MilvusVectorDB = init_milvus(db_path=db_path)
        for ticker in tickers.split(","):
            add_documents(db, embedding_fn, ticker.strip())

    output_fields: list[str] = ["text", "speaker", "year", "quarter", 
                                "transcript_index", "chunk_index"]
    res: list[list[dict]] = db.search(
        queries=query,
        embedding_fn=embedding_fn,
        # filter=f"ticker == '{ticker}'",
        output_fields=output_fields,
        limit=20,
    )
    file_name: str = llm.generate_filename(openai_client, query, ext=".yml")
    file_path: File = File(query_save_dir) / file_name
    logging.info("Saving query results to %s...", file_path)
    file_path.save(res[0])


if __name__ == "__main__":
    main()
