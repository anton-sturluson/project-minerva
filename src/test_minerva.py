"""Test script for Minerva knowledge base system."""

import asyncio

from minerva.clustering.threshold_selector import LocalMaximaSelector
from minerva.core.community import HLCDetector
from minerva.core.node import EntityNode
from minerva.minerva import Minerva

# Test samples - Financial report texts with overlapping entities
SAMPLE_TEXT_1 = """
Apple Inc. reported quarterly revenue of $119.6 billion for Q1 FY2024. iPhone sales
reached $69.7 billion, driven by strong demand in China and India. Services revenue,
including Apple Music, iCloud, and the App Store, grew to $23.1 billion. CEO Tim Cook
emphasized the company's focus on artificial intelligence integration, particularly
enhancing Siri capabilities.
"""

SAMPLE_TEXT_2 = """
Apple Inc. announced plans to invest $15 billion in expanding its Services division,
targeting growth in India, Brazil, and Indonesia. CEO Tim Cook outlined the vision
for Apple Music to reach 200 million subscribers by 2025. CFO Luca Maestri noted that
iCloud revenue grew 18% quarter-over-quarter. Goldman Sachs analysts raised their price
target, citing the recurring revenue stability provided by Services.
"""

SAMPLE_TEXT_3 = """
During its annual developer conference, Apple Inc. revealed a strategic partnership with
Microsoft to bring Xbox cloud gaming to the Apple Vision Pro. The announcement was made
by Tim Cook, who was joined on stage by Microsoft's CEO, Satya Nadella. This collaboration
aims to enhance the gaming experience on the new spatial computing device. Additionally,
upgrades to Siri were previewed, promising more natural conversations, powered by a new
on-device machine learning model developed in their labs in Cupertino.
"""

SAMPLE_TEXT_4 = """
The App Store generated $1.1 trillion in billings and sales in 2023, according to Apple Inc.
The platform hosts over 1.8 million apps serving more than 650 million weekly visitors. Epic
Games continues its legal battle over the 30% commission rate that Apple charges developers.
Apple's Phil Schiller defended the App Store model, emphasizing security and user privacy
protections. Meanwhile, smaller developers called for reduced fees, particularly for
subscription-based services that fall under Apple's Services revenue category.
"""


async def learn_texts() -> None:
    """Learn from sample texts and build knowledge graph."""
    minerva: Minerva = Minerva()

    try:
        print("Clearing existing graph...")
        await minerva.driver.clear_graph()
        print("Graph cleared.")

        print("Creating vector indexes...")
        await minerva.driver.create_vector_indexes()
        print("Vector indexes created.\n")

        texts: list[str] = [SAMPLE_TEXT_1, SAMPLE_TEXT_2, SAMPLE_TEXT_3]

        for i, text in enumerate(texts, 1):
            print(f"{'=' * 80}")
            print(f"Text {i}:")
            print(f"{text.strip()}\n")

            print(f"Learning from text {i}...")
            result: dict = await minerva.learn(text)

            entity_query: str = """
            MATCH (e:Entity)
            WHERE e.id IN $entity_ids
            RETURN e.id as id, e.name as name, e.summary as summary
            """
            entities: list[dict] = await minerva.driver.query(
                entity_query, {"entity_ids": result["entity_ids"]}
            )

            print(f"Extracted {len(entities)} entities:")
            for entity in entities:
                print(f"  - {entity['name']} (id={entity['id']}): {entity['summary']}")
            print()

            relation_query: str = """
            MATCH (e1:Entity)-[r:RELATES_TO]->(e2:Entity)
            WHERE r.id IN $relation_ids
            RETURN e1.name AS from_entity, r.relation_type AS relation_type, r.fact AS fact, e2.name AS to_entity
            """
            relations: list[dict] = await minerva.driver.query(
                relation_query, {"relation_ids": result["relation_ids"]}
            )

            if relations:
                print(f"Extracted {len(relations)} relations:")
                for rel in relations:
                    print(
                        f"  - ({rel['from_entity']})-[{rel['relation_type']}]->({rel['to_entity']}): {rel['fact']}"
                    )
                print()

    finally:
        print(f"\n{'=' * 80}")
        print("Closing connection...")
        await minerva.close()
        print("Done.")


async def detect_topics(top_k: int = 3) -> None:
    """Detect topics from existing knowledge graph."""
    from minerva.api.client import close_all_clients
    from minerva.core.topic import TopicManager
    from minerva.kb.driver import Neo4jDriver

    driver: Neo4jDriver = Neo4jDriver()

    try:
        print(f"{'=' * 80}")
        print("Topic Detection and Visualization")
        print(f"{'=' * 80}\n")

        print("Clearing existing topics...")
        await driver.clear_topics()
        print("Topics cleared.\n")

        print(
            f"Running hierarchical link clustering with LocalMaximaSelector(top_k={top_k})..."
        )
        threshold_selector: LocalMaximaSelector = LocalMaximaSelector(top_k=top_k)
        detector: HLCDetector = HLCDetector(driver)
        topic_manager: TopicManager = TopicManager(driver, detector)

        hierarchy = await topic_manager.detect(threshold_selector=threshold_selector)

        print(
            f"\nDetected {len(hierarchy.topics)} topics across {hierarchy.num_levels} levels"
        )
        print(f"Created {len(hierarchy.belongs_to_relations)} entity-topic assignments")
        print(
            f"Created {len(hierarchy.subtopic_relations)} parent-child topic relations\n"
        )

        topics_by_level: dict[int, list] = {}
        for topic in hierarchy.topics:
            if topic.level not in topics_by_level:
                topics_by_level[topic.level] = []
            topics_by_level[topic.level].append(topic)

        print("Topics by level:")
        for level in sorted(topics_by_level.keys()):
            print(f"\n  Level {level} ({len(topics_by_level[level])} topics):")
            for topic in topics_by_level[level]:
                if topic.level == 0:
                    entities_in_topic = await topic.get_entities(driver=driver)
                    entity_names = (
                        [e.name for e in entities_in_topic] if entities_in_topic else []
                    )
                    if entity_names:
                        print(f"    - {topic.name}: {', '.join(entity_names)}")
                    else:
                        print(f"    - {topic.name}: (no entities)")
                else:
                    children = await topic.get_children(driver=driver)
                    child_names = [c.name for c in children] if children else []
                    if child_names:
                        print(f"    - {topic.name}: [{', '.join(child_names)}]")
                    else:
                        print(f"    - {topic.name}: (no children)")

        print(f"\n{'=' * 80}")
        print("Topic Hierarchy Visualization")
        print(f"{'=' * 80}\n")

        print("Subtopic Relations:")
        for rel in hierarchy.subtopic_relations:
            child_topic = next(
                (t for t in hierarchy.topics if t.id == rel.from_id), None
            )
            parent_topic = next(
                (t for t in hierarchy.topics if t.id == rel.to_id), None
            )
            if child_topic and parent_topic:
                print(
                    f"  {child_topic.name} (L{child_topic.level}) → {parent_topic.name} (L{parent_topic.level})"
                )

    finally:
        print(f"\n{'=' * 80}")
        print("Closing connection...")
        await driver.close()
        await close_all_clients()
        print("Done.")


async def main() -> None:
    """Run both learning and topic detection."""
    await learn_texts()


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        if sys.argv[1] == "learn":
            asyncio.run(learn_texts())
        elif sys.argv[1] == "topics":
            top_k: int = int(sys.argv[2]) if len(sys.argv) > 2 else 3
            asyncio.run(detect_topics(top_k))
        else:
            print("Usage:")
            print(
                "  python src/test_minerva.py learn         # Learn from sample texts"
            )
            print(
                "  python src/test_minerva.py topics [K]    # Detect topics with top_k=K (default: 3)"
            )
    else:
        asyncio.run(main())
