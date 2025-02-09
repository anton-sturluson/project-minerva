"""Query Milvus Vector Database."""
import logging
from typing import Callable

import click

from knowledge.database.vector_db import MilvusVectorDB
from knowledge.llm import useful as llm
from knowledge.llm.client import OpenAIClient
from knowledge.util.env import OPENAI_API_KEY
from knowledge.util.file import File

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)
DEFAULT_COLLECTION_NAME: str = "demo_collection"

@click.command()
@click.option(
    "--query", type=str, required=True,
    help="Query to search for in the vector database")
@click.option(
    "--db-path", type=str, default="../data/milvus_demo.db",
    help=("Path to the Milvus Vector Database. If not provided, a new database "
          "will be created.  "))
@click.option(
    "--query-save-dir", type=str, default="../data/query_results",
    help="Directory to save query results")
def main(query: str, db_path: str, query_save_dir: str):
    logger.info("Loading Milvus Vector DB from %s...", db_path)
    db: MilvusVectorDB = MilvusVectorDB(db_path=db_path, collection_name=DEFAULT_COLLECTION_NAME)
    openai_client = OpenAIClient(api_key=OPENAI_API_KEY)
    embedding_fn: Callable = openai_client.get_embedding

    output_fields: list[str] = [
        "company_name", "year", "quarter", "text",
        "speaker", "speaker_index", "chunk_index", "topic"]
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
