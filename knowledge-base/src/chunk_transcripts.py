"""A script to chunk transcripts."""
from dataclasses import asdict
import json
import re
import time


import click
from openai.types import Batch, FileObject
from tqdm import tqdm

from minerva.llm.chunk import parse_chunk_output, gpt_chunk_prompt, ChunkOutput
from minerva.llm.client import OpenAIClient
from minerva.llm.useful import generate_topic
from minerva.knowledge.kb import CompanyKB
from minerva.util.env import OPENAI_API_KEY
from minerva.util.file import File


SLEEP_TIME: int = 60

# utility functions

def _get_num_sentences(text: str) -> int:
    """Count the number of sentences in the given text."""
    return len(re.split(r'[.!?]', text)) - 1


def _generate_missing_topics(chunk_output: ChunkOutput):
    """Generate topics for chunks that don't have one."""
    for chunk in chunk_output.chunks:
        if not chunk.get("chunk_topic"):
            chunk["chunk_topic"] = generate_topic(chunk["text"])

# OpenAI batch-related functions

def _build_request(
    request_id: str, 
    prompt: str,
    model_name: str = "gpt-4o",
    temperature: float = 0.3,
    max_tokens: int = 4096
) -> dict:
    """Build a OpenAI batch request for chunking."""
    return {
        "custom_id": request_id,
        "method": "POST",
        "url": "/v1/chat/completions",
        "body": {
            "model": model_name,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [
                {"role": "user", "content": prompt}
            ]
        }
    }


def _get_request_id(ticker: str, year: int, quarter: int, speaker_index: int) -> str:
    """Get a request ID for a given transcript."""
    return f"{ticker}-Y{year}-Q{quarter}-S{speaker_index}"


def _get_requests_from_one_transcript(
    ticker: str,
    transcript_map: dict, 
    failure_only: bool = False,
    min_sentences: int = 6
) -> list[dict]:
    """
    Get chunking requests for a transcript.

    Args:
        ticker: The ticker of the company.
        transcript_map: The transcript to chunk.
        failure_only: Whether to only include transcripts that failed to chunk.
        min_sentences: The minimum number of sentences required for chunking.
    """
    year: int = transcript_map["year"]
    quarter: int = transcript_map["quarter"]

    requests: list[dict] = []
    if failure_only:
        if "chunking_output" not in transcript_map:
            return requests
        failure_map: dict[str, bool] = {
            c["speaker_index"]: c["failure"] for c in transcript_map["chunking_output"]
        }

    for speaker_map in transcript_map["speakers"]:
        text: str = speaker_map["text"]
        speaker_index: int = speaker_map["speaker_index"]

        if failure_only:
            if not failure_map.get(speaker_index, False):
                continue
        else:
            num_sentences: int = _get_num_sentences(text)
            if num_sentences < min_sentences:
                continue

        prompt: str = gpt_chunk_prompt(speaker_map["text"])
        request_id: str = _get_request_id(ticker, year, quarter, speaker_index)
        requests.append(_build_request(request_id, prompt))

    return requests


def save_requests(
    kb: CompanyKB, 
    output_path: str,
    tickers: list[str] | None = None,
    min_sentences: int = 6,
    limit: int = -1,
    failure_only: bool = False
):
    """
    Build and save OpenAI chunking requests for all transcripts in the KB.

    Args:
        kb: The KB to save the requests for.
        output_path: The path to save the requests.
        tickers: The tickers to process.
        min_sentences: The minimum number of sentences required for chunking.
        limit: The number of transcripts to process.
        failure_only: Whether to only include transcripts that failed to chunk.
    """
    query = {}
    if tickers:
        query = {"ticker": {"$in": tickers}}
    cursor = kb.transcripts.find(query)
    if limit > 0:
        cursor = cursor.limit(limit)

    requests: list[dict] = []
    for company_map in cursor:
        ticker: str = company_map["ticker"]
        for transcript_map in company_map.get("transcripts", []):
            requests.extend(_get_requests_from_one_transcript(
                ticker, transcript_map, failure_only, min_sentences))

    if output_path:
        File(output_path).save(requests)

    print(f"`build_requests`: num requests: {len(requests)}")


def _get_batch(client: OpenAIClient, batch_id: str) -> Batch:
    """Get a batch from OpenAI."""
    return client.batches.retrieve(batch_id)


def _send_batch(client: OpenAIClient, output_path: str) -> Batch:
    """Send a batch to OpenAI."""
    batch_input_file: FileObject = client.files.create(
        file=open(output_path, "rb"),
        purpose="batch"
    )    
    file_id: str = batch_input_file.id

    batch: Batch = client.batches.create(
        input_file_id=file_id,
        endpoint="/v1/chat/completions",
        completion_window="24h"
    )
    return batch

# ingesting batch results

def _load_file(client: OpenAIClient, file_id: str) -> dict[str, dict]:
    """
    Load a batch file for a given file ID.

    Args:
        client: The OpenAI client.
        file_id: The file ID of the batch results.
    """
    file: FileObject = client.files.content(file_id)
    content_map: dict[str, dict] = {}
    for line in file.iter_lines():
        response: dict = json.loads(line)
        request_id: str = response["custom_id"]
        if "response" in response:
            response = response["response"]

        body: dict = response["body"]
        if "choices" in body:
            content: str = body["choices"][0]["message"]["content"]
        else:
            content: str = body["messages"][0]["content"]
        content_map[request_id] = content
    return content_map


def _ingest_one_transcript(ticker: str, transcript_map: dict, content_map: dict):
    """
    Ingest a transcript.

    Args:
        ticker: The ticker of the company.
        transcript_map: The transcript to ingest. It maps speaker index to 
            transcript dictionary.
        content_map: Mapping request ID to chunking output.
    """
    year: int = transcript_map["year"]
    quarter: int = transcript_map["quarter"]

    # if 'chunking_output' isn't there, this is the first time chunking
    is_init: bool = False
    if "chunking_output" not in transcript_map:
        is_init = True

    chunking_map: dict[int, dict] = {
        c["speaker_index"]: c for c in transcript_map.get("chunking_output", [])
    }

    for speaker_map in transcript_map.get("speakers", []):
        text: str = speaker_map["text"]
        speaker_index: int = speaker_map["speaker_index"]
        request_id: str = _get_request_id(ticker, year, quarter, speaker_index)

        if request_id in content_map:
            chunk_prompt_output: str = content_map[request_id]
            chunk_output: ChunkOutput = parse_chunk_output(text, chunk_prompt_output)
        elif is_init:
            chunk_output = ChunkOutput()
            chunk_output.add_chunk(text)
        else:
            continue

        chunk_output.speaker = speaker_map["speaker"]
        chunk_output.speaker_index = speaker_index
        _generate_missing_topics(chunk_output)
        chunking_map[speaker_index] = asdict(chunk_output)
    
    chunking_output: list[dict] = [chunking_map[i] for i in sorted(chunking_map.keys())]
    return chunking_output


def ingest(
    client: OpenAIClient, 
    kb: CompanyKB, 
    file_id: str, 
    tickers: list[str] | None = None
):
    """
    Ingest a batch of transcripts.

    Args:
        client: The OpenAI client.
        kb: The KB to ingest the transcripts.
        file_id: The file ID of the batch results.
        tickers: The tickers to process.
    """
    content_map: dict[str, dict] = _load_file(client, file_id)

    query = {}
    if tickers:
        query = {"ticker": {"$in": tickers}}
    cursor = kb.transcripts.find(query)

    for company_map in cursor:
        ticker: str = company_map["ticker"]
        print(f"`ingest`: Ticker: {ticker}")
        transcripts: list[dict] = company_map.get("transcripts", [])
        for transcript_map in tqdm(transcripts, desc="Processing transcripts"):
            transcript_map["chunking_output"] = _ingest_one_transcript(
                ticker, transcript_map, content_map)

        kb.add_transcripts(ticker, transcripts)


@click.command()
@click.option("--min-sentences", type=int, default=6, show_default=True,
              help="The minimum number of sentences required for chunking.")
@click.option("--output-path", type=str, show_default=True,
              default="../data/transcript_requests.jsonl",
              help="The path to save the transcript requests.")
@click.option("--limit", type=int, default=-1, show_default=True,
              help="The number of transcripts to process.")
@click.option("--file-id", type=str, default="", show_default=True,
              help="The file ID of the batch results to ingest.")
@click.option("--failure-only", is_flag=True, show_default=True,
              help="Only ingest transcripts that failed to chunk.")
@click.option("--tickers", type=str, default="all", show_default=True,
              help="The tickers to process (separated by comma).")
def main(
    min_sentences: int, 
    output_path: str, 
    limit: int, 
    file_id: str,
    failure_only: bool,
    tickers: str
):
    """Main function for chunking transcripts."""
    client = OpenAIClient(api_key=OPENAI_API_KEY)
    kb = CompanyKB()

    _tickers: list[str] | None = None
    if tickers != "all":
        _tickers = tickers.split(",")

    if not file_id:
        save_requests(kb, output_path, _tickers, min_sentences, limit, failure_only)
        batch: Batch = _send_batch(client, output_path)

        while batch.status not in ["completed", "failed"]:
            print(f"`main`: batch status: {batch.status}. Sleeping for {SLEEP_TIME} seconds...")
            time.sleep(SLEEP_TIME)
            batch: Batch = _get_batch(client, batch.id)
        print(f"`main`: batch status: {batch.status}")
        if batch.status == "failed":
            print(f"`main`: batch failed: {batch.error}")
            return
        file_id: str = batch.output_file_id

    print(f"`main`: ingesting batch results: {file_id}...")
    ingest(client, kb, file_id, _tickers)
    print("`main`: ingesting finished...")


if __name__ == "__main__":
    main()
