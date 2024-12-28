from minerva.llm.client import Client


def generate_filename(client: Client, text: str, ext: str = ".yml") -> str:
    """Generate a file name as a summary of the given text."""
    prompt: str = f"""
    Given the following text, generate a concise and clear file name that summarizes the key
    content in a format appropriate for saving as a file. The file name should be brief, avoid
    special characters (except hyphens or underscores), and reflect the primary topic or
    purpose of the text. It should be clear and recognizable, such that someone can infer the
    content of the file without opening it.

    <Example>
    Example Input:

    Text:
    Text: "the latest report on the fiscal year 2024, including revenue growth,
           operating margins, and projections for Q4."
    Example Output: FY2024-Revenue-Growth-Q4-Projections
    </Example>

    Text:
    "{text}"
    """
    return client.get_completion(prompt) + ext


def try_test_prompt(client: Client) -> str:
    prompt: str = "Do not return anything."
    return client.get_completion(prompt)
