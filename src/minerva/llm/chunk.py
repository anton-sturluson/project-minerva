from dataclasses import dataclass, field
import re

import yaml

from minerva.llm.client import Client, AnthropicClient, OpenAIClient
from minerva.llm.useful import try_test_prompt
from minerva.util.env import ANTHROPIC_API_KEY, OPENAI_API_KEY
from minerva.util.env import TEST_MODE


@dataclass
class ChunkOutput:
    chunks: list[dict] = field(default_factory=list)
    chunk_prompt_output: str = ""
    preprocessed_prompt_output: str = ""
    failure: bool = False
    speaker: str = "" # need to be updated by caller
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

    def _preprocess_text(self, text: str) -> str:
        """Preprocess the text to remove special characters."""
        if text.startswith(("'", '"', '“', '”')):
            text = text[1:]
        if text.endswith(("'", '"', '“', '”')):
            text = text[:-1]
        return text


# mysteries... why does Claude perform better when it creates its own prompt?
# similarly, why does GPT perform better when it creates its own prompt?
def claude_chunk_prompt(text: str) -> str:
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
    Each entry should include a chunk index, chunk topic, the chunk text, and the source of the 
    chunk. Ensure that the chunks collectively cover all the information in the original text 
    without redundancy or hallucination.

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

    Remember to use only the information provided in the original text, without adding 
    any external knowledge or hallucinated content. Prioritize completeness and coherence 
    of ideas in your chunking.

    Please proceed with your analysis and chunking of the provided text.
    """


def gpt_chunk_prompt(text: str) -> str:
    return f"""
    You are an expert system designed to extract and structure data from complex texts. Your task is to analyze the following text and divide it into meaningful chunks of information.

    Here is the text to analyze:

    <text_to_analyze>
    {text}
    </text_to_analyze>

    Instructions:
    1. Read through the entire text carefully.
    2. **Create chunks**:
        - Do not alter the original text. Present as is.
       - Each chunk should focus on one key idea, fact, metric, event, or concept.
       - If necessary, a chunk may span multiple sentences or even a paragraph to maintain coherence.
       - Ensure all content from the original text is captured, without redundancy or hallucination.
    3. **Review your chunks**:
       - After creating the chunks, review them to ensure completeness and coherence.
       - Resolve any overlaps between chunks and ensure no information is missing.
       - If a chunk is too general or lacks specific content, assign it the topic `"Generic Topic"`.

    Output Format:
    After your analysis and chunking, present each chunk in the following YAML-like structure. 
    The output should be compatible with YAML. 
    **DO NOT** start or end with special characters like '```' or '```yaml' or '<output>' or '</output>'.

    <output>
    - chunk_topic: "Generic Topic"
      chunk: "Text for generic chunk if content is lacking or overly broad"
    - chunk_topic: "Specific Topic"
      chunk: "Text for chunk with more specific content"
    </output>

    **Important**: 
    1. Enclose each `chunk` in double quotations to ensure YAML compatibility. 
        This will prevent issues with special characters during YAML decoding.
    2. Ensure proper indentation for YAML files:
       - The `-` character for each chunk should align at the same level of indentation.
       - The `chunk_topic` and `chunk` should be indented by 2 spaces beneath the `-`.

    Please proceed with your analysis and chunking of the provided text.
    """


def chunk_text(
    text: str,
    model_name: str = "gpt-4o",
    temperature: float = 0.3,
    max_tokens: int = 16_384,
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
    if model_name.startswith("claude"):
        prompt: str = claude_chunk_prompt(text)
        client = AnthropicClient(api_key=ANTHROPIC_API_KEY)
    elif model_name.startswith("gpt"):
        prompt: str = gpt_chunk_prompt(text)
        client = OpenAIClient(api_key=OPENAI_API_KEY)
    else:
        raise ValueError(f"Invalid model name: {model_name}")
    
    if TEST_MODE:
        return try_test_prompt(client)
    return client.get_completion(prompt, model=model_name,
                                 temperature=temperature, max_tokens=max_tokens)


def preprocess_prompt_output(text: str) -> str:
    """
    Preprocess the prompt output to get the chunked text.
    """
    # First, remove the <output> and </output> tags
    cleaned_text = re.sub(r'<output>\s*|\s*</output>', '', text)
    
    # Then, remove any code blocks marked with ```yaml or other code types
    cleaned_text = re.sub(r'```.*?\n(.*?)\n```', r'\1', cleaned_text, flags=re.DOTALL)
    
    return cleaned_text


def parse_chunk_output(original_text: str, chunk_prompt_output: str) -> dict[str, dict]:
    """
    Parse the given text into a list of chunks.

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
            "failure": bool # whether the chunking process failed
        }
        ```
        In case of failures, the text will be the original text and the 
        chunk topic will be an empty string.
    """
    output: ChunkOutput = ChunkOutput()
    output.add_chunk(original_text)
    output.chunk_prompt_output = chunk_prompt_output

    preprocessed_prompt_output: str = preprocess_prompt_output(chunk_prompt_output)
    output.preprocessed_prompt_output = preprocessed_prompt_output

    try:
        if TEST_MODE:
            output.chunks = chunk_prompt_output
        else:
            chunks: list[dict] = yaml.safe_load(preprocessed_prompt_output)
            output.reset_chunks()
            for chunk in chunks:
                output.add_chunk(chunk["chunk"], chunk["chunk_topic"])
        output.failure = False
        return output

    except yaml.YAMLError as e:
        print(f"`chunk_and_parse_output`: Error loading YAML: {e}")
        output.failure = True
        return output
