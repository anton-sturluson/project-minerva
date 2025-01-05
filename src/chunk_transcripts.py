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

def _get_request(
    request_id: str, 
    prompt: str,
    model_name: str = "gpt-4o",
    temperature: float = 0.3,
    max_tokens: int = 4096
) -> dict:
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
    return f"{ticker}-Y{year}-Q{quarter}-S{speaker_index}"


def save_requests(
    kb: CompanyKB, 
    output_file_path: str,
    min_sentences: int = 6,
    limit: int = -1
):
    cursor = kb.transcripts.find()
    if limit > 0:
        cursor = cursor.limit(limit)

    requests: list[dict] = []
    for company_map in cursor:
        ticker: str = company_map["ticker"]
        print("Ticker:", ticker)
        for transcript_map in company_map.get("transcripts", []):
            year: int = transcript_map["year"]
            quarter: int = transcript_map["quarter"]
            for speaker_map in transcript_map["speakers"]:
                text: str = speaker_map["text"]
                num_sentences: int = _get_num_sentences(text)
                if num_sentences < min_sentences:
                    continue

                request_id: str = _get_request_id(ticker, year, quarter, 
                                                  speaker_map["speaker_index"])
                prompt: str = gpt_chunk_prompt(speaker_map["text"])
                requests.append(_get_request(request_id, prompt))

    if output_file_path:
        File(output_file_path).save(requests)

    print(f"`build_requests`: num requests: {len(requests)}")


def _get_batch(client: OpenAIClient, batch_id: str) -> Batch:
    return client.batches.retrieve(batch_id)


def send_batch(client: OpenAIClient, output_file_path: str) -> Batch:
    batch_input_file: FileObject = client.files.create(
        file=open(output_file_path, "rb"),
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


def ingest(client: OpenAIClient, kb: CompanyKB, file_id: str):
    content_map: dict[str, dict] = _load_file(client, file_id)

    for company_map in kb.transcripts.find():
        ticker: str = company_map["ticker"]
        print("Ticker:", ticker)
        transcripts: list[dict] = company_map.get("transcripts", [])
        for transcript_map in tqdm(transcripts, desc="Processing transcripts"):
            year: int = transcript_map["year"]
            quarter: int = transcript_map["quarter"]
            transcript_map["chunking_output"] = []
            if "transcript" in transcript_map:
                del transcript_map["transcript"]
            for speaker_map in transcript_map.get("speakers", []):
                speaker_index: int = speaker_map["speaker_index"]
                request_id: str = _get_request_id(ticker, year, quarter, speaker_index)

                if request_id in content_map:
                    chunk_prompt_output: str = content_map[request_id]
                    chunk_output: ChunkOutput = parse_chunk_output(
                        speaker_map["text"], chunk_prompt_output)
                else:
                    chunk_output = ChunkOutput()
                    chunk_output.add_chunk(speaker_map["text"])

                chunk_output.speaker = speaker_map["speaker"]
                chunk_output.speaker_index = speaker_index
                _generate_missing_topics(chunk_output)
                transcript_map["chunking_output"].append(asdict(chunk_output))

        kb.add_transcripts(ticker, transcripts)


@click.command()
@click.option("--min-sentences", type=int, default=6)
@click.option("--output-file-path", type=str, 
              default="../data/transcript_requests.jsonl")
@click.option("--limit", type=int, default=-1)
@click.option("--file-id", type=str, default="")
def main(
    min_sentences: int, 
    output_file_path: str, 
    limit: int, 
    file_id: str
):
    client = OpenAIClient(api_key=OPENAI_API_KEY)
    kb = CompanyKB()

    if not file_id:
        save_requests(kb, output_file_path, min_sentences, limit)
        batch: Batch = send_batch(client, output_file_path)

        while batch.status != "completed":
            print(f"`main`: batch status: {batch.status}. Sleeping for {SLEEP_TIME} seconds...")
            time.sleep(SLEEP_TIME)
            batch: Batch = _get_batch(client, batch.id)
        print(f"`main`: batch successful: {batch.id}")
        file_id: str = batch.output_file_id

    print(f"`main`: ingesting batch results: {file_id}...")
    ingest(client, kb, file_id)
    print("`main`: ingesting finished...")


if __name__ == "__main__":
    main()
