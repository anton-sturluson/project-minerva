#!/usr/bin/env python
import sys
import warnings

from earnings_digest.crew import EarningsDigest

warnings.filterwarnings("ignore", category=SyntaxWarning, module="pysbd")

# Initialize the transcript retriever
# This main file is intended to be a way for you to run your
# crew locally, so refrain from adding unnecessary logic into this file.
# Replace with inputs you want to test with, it will automatically
# interpolate any tasks and agents information

def run():
    """
    Run the crew.
    """
    # Get the most recent transcript for GOOG
    results = retriever.search(
        query="",  # Empty query to get most recent
        ticker="GOOG",
        limit=1
    )
    if not results:
        raise ValueError("No transcript found for GOOG")
        
    transcript = results[0]["text"]
    inputs = {
        'earnings_call_transcript': transcript
    }
    EarningsDigest().crew().kickoff(inputs=inputs)


def train():
    """
    Train the crew for a given number of iterations.
    """
    inputs = {
        "topic": "AI LLMs"
    }
    try:
        EarningsDigest().crew().train(n_iterations=int(sys.argv[1]), filename=sys.argv[2], inputs=inputs)

    except Exception as e:
        raise Exception(f"An error occurred while training the crew: {e}")

def replay():
    """
    Replay the crew execution from a specific task.
    """
    try:
        EarningsDigest().crew().replay(task_id=sys.argv[1])

    except Exception as e:
        raise Exception(f"An error occurred while replaying the crew: {e}")

def test():
    """
    Test the crew execution and returns the results.
    """
    inputs = {
        "topic": "AI LLMs"
    }
    try:
        EarningsDigest().crew().test(n_iterations=int(sys.argv[1]), openai_model_name=sys.argv[2], inputs=inputs)

    except Exception as e:
        raise Exception(f"An error occurred while replaying the crew: {e}")
