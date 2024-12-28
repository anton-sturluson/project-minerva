import re

import yaml

from minerva.llm.client import Client, AnthropicClient
from minerva.llm.useful import try_test_prompt
from minerva.util.env import ANTHROPIC_API_KEY
from minerva.util.env import TEST_MODE


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
    - chunk_topic: Generic Topic 0
      chunk: Generic text for chunk 0
    - chunk_topic: Generic Topic 1
      chunk: Generic text for chunk 1
    - chunk_topic: Generic Topic 2
      chunk: Generic text for chunk 2
    </output>

    Remember to use only the information provided in the original text, without adding any external knowledge or hallucinated content. Prioritize completeness and coherence of ideas in your chunking.

    Please proceed with your analysis and chunking of the provided text.
    """


def chunk_text(text: str, client: Client | None = None) -> str:
    if not client:
        client = AnthropicClient(api_key=ANTHROPIC_API_KEY)
    if TEST_MODE:
        return try_test_prompt(client)
    return client.get_completion(chunk_prompt(text))


def parse_prompt_output(text: str) -> str | None:
    output_match = re.search(r'<output>(.*?)</output>', text, re.DOTALL)
    if not output_match:
        return None
    return output_match.group(1)


def chunk_and_parse_output(text: str, client: Client | None = None) -> list[dict]:
    """
    Chunk the given text and parse the output into a list of chunks.

    Returns:
        A list of chunks information in the format of
        ```python
        [
            {
                "chunk_topic": str,
                "chunk": str,
                "chunk_index": int
            }
        ]
        ```
        In case of failures, the output will be either a parsed output
        or prompt output of the chunking process.
    """
    chunk_output: str = chunk_text(text, client)
    parsed_output: str | None = parse_prompt_output(chunk_output)
    if parsed_output is None:
        print(f"`chunk_and_parse_output`: Failed to parse output: {chunk_output}")
        return [chunk_output]

    try:
        if not TEST_MODE:
            chunks: list[dict] = yaml.safe_load(parsed_output)
            for i, chunk in enumerate(chunks):
                chunk["chunk_index"] = i
            return chunks
        return [parsed_output]
    except yaml.YAMLError as e:
        print(f"`chunk_and_parse_output`: Error loading YAML: {e}")
        return [parsed_output]
