from dataclasses import dataclass, field
import re

import yaml

from minerva.llm.client import Client, AnthropicClient
from minerva.llm.useful import try_test_prompt
from minerva.util.env import ANTHROPIC_API_KEY
from minerva.util.env import TEST_MODE


@dataclass
class ChunkOutput:
    chunks: list[dict] = field(default_factory=list)
    chunk_prompt_output: str = ""
    parsed_output: str = ""
    failure: bool = False
    speaker_index: int = -1 # need to be updated by caller

    def add_chunk(self, text: str, topic: str = ""):
        """Add a chunk to the list."""
        self.chunks.append({
            "text": text,
            "chunk_topic": topic,
            "chunk_index": len(self.chunks),
        })
    
    def reset_chunks(self):
        """Reset the chunks list."""
        self.chunks = []


def chunk_prompt(text: str) -> str:
    return f"""
    You are an expert system designed to extract and structure data from complex texts. Your task is to analyze the following text and divide it into meaningful chunks of information:

    Here is the text to analyze:

    <text_to_analyze>
    {text}
    </text_to_analyze>

    Instructions:
    1. Read through the entire text carefully.
    2. Identify key pieces of information, including facts, metrics, events, and concepts.
    3. Create chunks of information, where each chunk:
       - Focuses on a single, key piece of information or concept
       - Contains enough context to fully convey the information
       - May span multiple sentences or even a small paragraph if necessary
       - Does not overlap with other chunks
    4. Ensure that all content from the original text is included in the output.
    5. Make sure not to include special characters inappropriate for yaml files,
       such as ':', '|', and '='.

    Before providing your final output, wrap your analysis inside <text_breakdown> tags:
    1. Create a high-level outline of the main topics or themes in the text.
    2. For each main topic:
       - List the key information points
       - Group related information
       - Form initial chunks and explain your rationale for each
    3. Review your chunks to ensure they capture complete ideas and meet all criteria.
    4. Cross-check that all information from the original text is included in your chunks.
    5. Identify and resolve any potential overlaps between chunks.
    6. If necessary, refine your chunks based on this review.

    It's OK for this section to be quite long, as a thorough analysis will lead to better chunking.

    Output Format:
    After your analysis, present each chunk in a YAML-like structure with numbered entries. 
    Each entry should include a chunk index, chunk topic, the chunk text, and the soure of . Ensure that the chunks collectively cover all the information in the original text without redundancy or hallucination.

    Example output structure (using generic content):

    <text_breakdown>
    [Your detailed analysis as per the instructions above]
    </text_breakdown>

    <output>
    - chunk_topic: Topic 0
      chunk: Text for chunk 0
    - chunk_topic: Topic 1
      chunk: Text for chunk 1
    - chunk_topic: Topic 2
      chunk: Text for chunk 2
    </output>

    Remember to use only the information provided in the original text, without adding any external knowledge or hallucinated content. Prioritize completeness and coherence of ideas in your chunking.

    Please proceed with your analysis and chunking of the provided text.
    """


def chunk_text(
    text: str,
    client: Client | None = None,
    model_name: str = "claude-3-5-sonnet-latest",
    temperature: float = 0.3,
    max_tokens: int = 4096,
) -> str:
    """
    Chunk the given text using the specified LLM client.

    Args:
        text: The text to chunk.
        client: The LLM client to use. Defaults to AnthropicClient.
        model_name: The model to use. Defaults to "claude-3-5-sonnet-latest".
        temperature: The temperature to use. Defaults to 0.3.
        max_tokens: The maximum number of tokens to generate. Defaults to 4096.

    Returns:
        str: The chunked text.

    Raises:
        Exception: If the LLM fails to chunk the text. Exception
            depends on the LLM client.
    """
    if not client:
        client = AnthropicClient(api_key=ANTHROPIC_API_KEY)
    if TEST_MODE:
        return try_test_prompt(client)
    return client.get_completion(chunk_prompt(text), model=model_name,
                                 temperature=temperature, max_tokens=max_tokens)


def parse_prompt_output(text: str) -> str | None:
    """
    Parse the prompt output to get the chunked text.
    """
    output_match = re.search(r'<output>(.*?)</output>', text, re.DOTALL)
    if not output_match:
        return None
    return output_match.group(1)


def chunk_and_parse_output(text: str, client: Client | None = None) -> dict[str, dict]:
    """
    Chunk the given text and parse the output into a list of chunks.

    Returns:
        A dictionary with the following structure:
        ```python
        {
            "chunks": [ # list of chunked text and metadata
                {
                    "chunk_topic": str,
                    "text": str,
                    "chunk_index": int,
                }
            ],
            "chunk_prompt_output": str # the prompt output of the chunking process
            "parsed_output": str # parsing-attempted output from the chunk prompt output
            "failure": bool # whether the chunking process failed
        }
        ```
        In case of failures, the text will be the original text and the 
        chunk topic will be an empty string.
    """
    output: ChunkOutput = ChunkOutput()
    output.add_chunk(text)

    try:
        chunk_output: str = chunk_text(text, client)
    except Exception as e:
        print(f"`chunk_and_parse_output`: Error chunking text: {e}")
        output.failure = True
        return output

    output.chunk_prompt_output = chunk_output

    parsed_output: str | None = parse_prompt_output(chunk_output)
    output.parsed_output = parsed_output

    if parsed_output is None:
        output.failure = True
        print(f"`chunk_and_parse_output`: Failed to parse prompt output: {chunk_output}")
        return output

    try:
        if TEST_MODE:
            output.chunks = parsed_output
        else:
            chunks: list[dict] = yaml.safe_load(parsed_output)
            output.reset_chunks()
            for chunk in chunks:
                output.add_chunk(chunk["chunk"], chunk["chunk_topic"])
        output.failure = False
        return output

    except yaml.YAMLError as e:
        print(f"`chunk_and_parse_output`: Error loading YAML: {e}")
        output.failure = True
        return output
