import os

from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY")
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY")
TEST_MODE: bool = os.getenv("TEST_MODE", "false").lower() == "true"
