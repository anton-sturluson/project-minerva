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


def _init(
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
    schema.add_field(field_name="speaker_index", datatype=DataType.INT64)
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


def _get_text_to_embed(
    ticker: str,
    company: str, 
    speaker: str,
    fiscal_year: int,
    quarter: int,
    topic: str, 
    text: str
) -> str:
    """
    Transform transcript into a format to embed into Milvus.
    """
    company_info: str = f"company: {company} (ticker: {ticker})"
    fiscal_info: str = f"FY{fiscal_year} Q{quarter}"
    speaker_info: str = f"speaker: {speaker}, topic: {topic}"
    return f"[{company_info}, {fiscal_info}, {speaker_info}]\n{text}"


def add_documents(
    db: MilvusVectorDB,
    kb: CompanyKB,
    embedding_fn: Callable,
    ticker: str
):
    """Add documents in the KB to Milvus Vector Database."""
    query = {"ticker": ticker}
    for company_map in tqdm(kb.transcripts.find(query), desc="Adding documents"):
        company_name: str = company_map["company_name"]
        for transcript_map in tqdm(company_map["transcripts"], desc="Adding transcripts"):
            year: int = transcript_map["year"]
            quarter: int = transcript_map["quarter"]

            docs: list[str] = []
            metadata: list[dict] = []
            for chunk_map in transcript_map.get("chunking_output", []):
                speaker: str = chunk_map.get("speaker", "")

                for chunk in chunk_map.get("chunks", []):
                    text: str = chunk.get("text")
                    topic: str = chunk.get("chunk_topic", "")
                    if not text:
                        continue

                    embed_text: str = _get_text_to_embed(
                        ticker, company_name, speaker, year, quarter, topic, text)
                    docs.append(embed_text)
                    metadata.append({
                        "text": embed_text,
                        "ticker": ticker,
                        "company_name": company_name,
                        "speaker": speaker,
                        "year": year,
                        "quarter": quarter,
                        "speaker_index": chunk_map["speaker_index"],
                        "chunk_index": chunk["chunk_index"]
                    })

            db.add_documents(
                documents=docs,
                metadata=metadata,
                embedding_fn=embedding_fn
            )


@click.command()
@click.option(
    "--force-init", type=bool, is_flag=True,
    help="Whether to force initializing the Milvus Vector Database")
@click.option(
    "--query", type=str, default="",
    help="Query to search for in the vector database")
@click.option(
    "--tickers", type=str, default="all",
    help="Ticker of the companies (separated by comma) to include")
@click.option(
    "--db-path", type=str, default="../data/milvus_demo.db",
    help=("Path to the Milvus Vector Database. If not provided, a new database "
          "will be created.  "))
@click.option(
    "--query-save-dir", type=str, default="../data/query_results",
    help="Directory to save query results")
def main(force_init: bool, query: str, tickers: str, db_path: str, query_save_dir: str):
    kb = CompanyKB()
    openai_client = OpenAIClient(api_key=OPENAI_API_KEY)
    embedding_fn: Callable = openai_client.get_embedding

    if not force_init and File(db_path).exists:
        logger.info("Loading Milvus Vector DB from %s...", db_path)
        db: MilvusVectorDB = MilvusVectorDB(
            db_path=db_path, collection_name=DEFAULT_COLLECTION_NAME)
    else:
        if not db_path:
            db_path = DEFAULT_DB_PATH
        logger.info("Initializing Milvus Vector Database...")
        db: MilvusVectorDB = _init(db_path=db_path)
        if tickers == "all":
            tickers = kb.unique_tickers
        else:
            tickers = tickers.split(",")

        for ticker in tickers:
            add_documents(db, kb, embedding_fn, ticker)

    if query:
        output_fields: list[str] = [
            "company_name", "year", "quarter", "text",
            "speaker", "speaker_index", "chunk_index", "text"]
        res: list[list[dict]] = db.search(
            queries=query,
            embedding_fn=embedding_fn,
            # filter=f"ticker == '{ticker}'",
            output_fields=output_fields,
            limit=50,
        )
        res = res[0][::-1] # FIXME
        file_name: str = llm.generate_filename(query, ext=".yml")
        file_path: File = File(query_save_dir) / file_name
        logging.info("Saving query results to %s...", file_path)
        file_path.save(res)


if __name__ == "__main__":
    main()
