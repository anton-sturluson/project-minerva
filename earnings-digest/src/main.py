#!/usr/bin/env python
from pathlib import Path
import sys
import warnings

import click
from minerva_knowledge.database import CompanyKB

from earnings_digest.crew import EarningsDigest

warnings.filterwarnings("ignore", category=SyntaxWarning, module="pysbd")

# Initialize the transcript retriever
# This main file is intended to be a way for you to run your
# crew locally, so refrain from adding unnecessary logic into this file.
# Replace with inputs you want to test with, it will automatically
# interpolate any tasks and agents information


@click.command()
@click.option(
    "--ticker", type=str, required=True, help="Ticker to create earnings digest for"
)
@click.option("--year", type=int, help="Year to create earnings digest for")
@click.option("--quarter", type=int, help="Quarter to create earnings digest for")
@click.option("--use-most-recent", is_flag=True, help="Use the most recent transcript")
@click.option(
    "--output-dir",
    type=click.Path(path_type=Path),
    default="output",
    help="Directory to save the output",
)
def run(ticker: str, year: int, quarter: int, use_most_recent: bool, output_dir: Path):
    """
    Run the crew.
    """
    if not output_dir.exists():
        output_dir.mkdir(parents=True)

    kb = CompanyKB()
    if use_most_recent:
        transcript: dict | None = kb.get_transcript(ticker, most_recent=True)
    else:
        transcript: dict | None = kb.get_transcript(ticker, year, quarter)

    if not transcript:
        raise ValueError(f"No transcript found for {ticker} (Y{year} Q{quarter})")

    inputs = {"earnings_call_transcript": transcript["full_transcript"]}
    earnings_digest = EarningsDigest(output_dir, ticker)
    earnings_digest.crew().kickoff(inputs=inputs)


def train():
    """
    Train the crew for a given number of iterations.
    """
    inputs = {"topic": "AI LLMs"}
    try:
        EarningsDigest().crew().train(
            n_iterations=int(sys.argv[1]), filename=sys.argv[2], inputs=inputs
        )

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
    inputs = {"topic": "AI LLMs"}
    try:
        EarningsDigest().crew().test(
            n_iterations=int(sys.argv[1]), openai_model_name=sys.argv[2], inputs=inputs
        )

    except Exception as e:
        raise Exception(f"An error occurred while replaying the crew: {e}")


if __name__ == "__main__":
    run()  # pylint: disable=no-value-for-parameter
