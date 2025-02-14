"""Utility functions to deal with clarity output."""


def get_explanation(collection, pubmed_id: str) -> str:
    """Get explanation from Clarity output for a given pubmed id."""
    query = {"pubmed_id": pubmed_id}
    out = collection.find_one(query)
    if not out:
        raise ValueError(f"No Clarity output found for pubmed_id={pubmed_id}")

    runs: list[dict] = out.get("pipeline_runs", [])
    if not runs:
        raise ValueError(f"No pipeline runs found for pubmed_id={pubmed_id}")

    if "explanation" not in runs[-1]:
        raise ValueError(f"No explanation found for pubmed_id={pubmed_id}")

    return runs[-1]["explanation"]
