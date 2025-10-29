"""Simple script to test topic hierarchy export."""

import asyncio

from minerva.kb.driver import Neo4jDriver
from minerva.kb.exporter import Exporter


async def main() -> None:
    """Export topic hierarchy to markdown."""
    driver: Neo4jDriver = Neo4jDriver()
    exporter: Exporter = Exporter(driver)

    try:
        print("Exporting topic hierarchy to markdown...")
        await exporter.export_to_markdown("export.md")
        print("Export completed! Check 'export.md' for results.")
    finally:
        await driver.close()


if __name__ == "__main__":
    asyncio.run(main())
