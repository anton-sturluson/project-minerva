"""Client wrappers for various database connections."""
__all__ = ["MongoClientWrapper"]
from pymongo import MongoClient

from . import constant as C


class MongoClientWrapper:
    """
    MongoDB client wrapper that connects to the MongoDB server and provides
    access to the databases and collections. Jona's MongoDB knowledge base
    is structured as follows:
    - Persistent DB stores the data that do not change with the KB version.
        These include organisms (taxonomic information), journals, and papers.
        These data don't change once stored in the database and are used
        across all KB versions.
    - Variable DB stores the data that change with the KB version. These
        include insights, conditions, symptoms, sensitivities, metabolisms,
        diets, treatments, and lifestyles. These often change with the KB
        version and are stored in separate databases for each KB version.
    - Insight DB stores insights from the literature. Since insights
            are often manipulated for testing purposes, we provide
            more flexibility by letting users choose which database
            or collection name to use for insight

    Args:
        uri: URI to connect to the MongoDB server. If None, it uses the
        persistent_db: Name of the persistent database. If None, it uses
            the default 'persistent_db' database.
        user_db: Name of the user/report database. This is by default set to
            'jona' and contains information about user reports.
        variable_db: Name of the variable database. If None, it uses the
            persistent database as a default behavior.
        insight_db: Name of the insight database. If None, it uses the
            persistent database as a default behavior.
        insight_collection_name: Name of the insight collection. If None, it
            uses the default 'insights' collection.
    Attributes:
        client: MongoDB client to connect to the MongoDB server.

    """
    persistent_collections = [
        C.REPORTS, C.INSIGHTS, C.ORGANISMS,
        C.JOURNALS, C.PAPERS, C.METRICS, C.FOOD_CATEGORIES
    ]
    variable_collections = [
        C.HEALTH_CATEGORIES, C.HEALTH_CONCERNS,
        C.FOOD_DIGESTIONS, C.ACTIONS
    ]

    def __init__(
        self,
        uri: str | None = None,
        persistent_db: str = "persistent_db",
        user_db: str = "jona",
        variable_db: str | None = None,
        insight_db: str | None = None,
        insight_collection_name: str = "insights"
    ):
        if uri is None:
            self.client = MongoClient()
        else:
            self.client = MongoClient(uri)

        self.persistent_db = self.client[persistent_db]
        self.user_db = self.client[user_db]

        if variable_db is not None:
            self.variable_db = self.client[variable_db]
        else:
            self.variable_db = self.client[persistent_db]

        if insight_db is not None:
            self.insight_db = self.client[insight_db]
        else:
            self.insight_db = self.client[persistent_db]

        self.insight_collection_name = insight_collection_name

    def __getitem__(self, db_name: str):
        """Get the database with the given name."""
        return self.client[db_name]

    def get_collection(self, collection_name: str):
        """
        Get the collection with the given name. If the collection name
        cannot be found from both persistent and variable databases,
        default to variable DB.
        """
        if collection_name in [self.insight_collection_name, C.INSIGHTS]:
            return self.insight_db[self.insight_collection_name]
        if collection_name in self.persistent_collections:
            return self.persistent_db[collection_name]
        return self.variable_db[collection_name]

    def list_database_names(self) -> list[str]:
        """List the database names in the client."""
        yield from self.client.list_database_names()

    def list_collections(
        self,
        exclude_variable: bool = False,
        exclude_persistent: bool = False
    ):
        """
        List MongoDB collections. If `exclude_variable` is True, exclude
        collections in the variable database. If `exclude_persistent` is
        True, exclude collections in the persistent database.

        Args:
            exclude_variable: If True, exclude collections in the variable
                database.
            exclude_persistent: If True, exclude collections in the persistent
                database.

        Returns:
            A generator of MongoDB collections.
        """
        if not exclude_persistent:
            for collection in self.persistent_collections:
                yield self.persistent_db[collection]


        if not exclude_variable:
            for collection in self.variable_collections:
                yield self.variable_db[collection]

    def drop_database(self, db_name: str):
        """Drop the database with the given name."""
        self.client.drop_database(db_name)

    def close(self):
        """Close the MongoDB client."""
        self.client.close()

    @staticmethod
    def is_persistent_collection(collection_name: str) -> bool:
        """Check if the collection name is in the persistent collections."""
        return collection_name in MongoClientWrapper.persistent_collections

    # utility functions

    def save_versioned_insights(self, version: str):
        """
        Save the versioned insights collection by storing the current insights
        into a new collection inside `self.versioned_insight_db` with the
        given version name.
        """
        assert version, f"version={version} ({type(version)}"
        pipeline= [
            {
                "$merge": {
                    "into": {
                        "db": C.VERSIONED_INSIGHTS,
                        "coll": version
                    },
                    "whenMatched": "replace",
                    "whenNotMatched": "insert"
                }
            }
        ]
        self.insights.aggregate(pipeline)

    # collections in the persistent database

    @property
    def reports(self):
        """Reports collection storing user microbiome reports."""
        return self.persistent_db.reports

    @property
    def insights(self):
        """Insights collection."""
        return self.insight_db[self.insight_collection_name]

    @property
    def organism_insights(self):
        """Organism insights collection."""
        return self.persistent_db.organism_insights

    @property
    def organisms(self):
        """Organisms collection."""
        return self.persistent_db.organisms

    @property
    def organism_metadata(self):
        """Organism metadata collection."""
        return self.persistent_db.organism_metadata

    @property
    def journals(self):
        """Journals collection."""
        return self.persistent_db.journals

    @property
    def papers(self):
        """Papers collection."""
        return self.persistent_db.papers

    @property
    def metrics(self):
        """Metrics collection."""
        return self.persistent_db.metrics

    @property
    def food_categories(self):
        """Food categories collection."""
        return self.persistent_db.food_categories

    @property
    def mesh_ontology(self):
        """Ontology for all MeSH records."""
        return self.persistent_db.mesh_ontology

    @property
    def ncbi_taxonomy(self):
        """NCBI taxonomy collection."""
        return self.persistent_db.ncbi_taxonomy

    # collections in the variable database

    @property
    def health_categories(self):
        """Health categories collection."""
        return self.variable_db.health_categories

    @property
    def health_concerns(self):
        """Health concerns collection."""
        return self.variable_db.health_concerns

    @property
    def food_digestions(self):
        """Food digestions collection."""
        return self.variable_db.food_digestions

    @property
    def actions(self):
        """Actions collection."""
        return self.variable_db.actions

    # collections in the variable db but are deprecated in 'v3'

    @property
    def conditions(self):
        """Conditions collection."""
        raise DeprecationWarning(
            "`conditions` collection is deprecated in 'v3'.")

    @property
    def symptoms(self):
        """Symptoms collection."""
        raise DeprecationWarning(
            "`symptoms` collection is deprecated in 'v3'.")

    @property
    def sensitivities(self):
        """Sensitivities collection."""
        raise DeprecationWarning(
            "`sensitivities` collection is deprecated in 'v3'.")

    @property
    def metabolisms(self):
        """Metabolisms collection."""
        raise DeprecationWarning(
            "`metabolisms` collection is deprecated in 'v3'.")

    @property
    def diets(self):
        """Diets collection."""
        raise DeprecationWarning("`diets` collection is deprecated in 'v3'.")

    @property
    def treatments(self):
        """Treatments collection."""
        raise DeprecationWarning(
            "`treatments` collection is deprecated in 'v3'.")

    @property
    def lifestyles(self):
        """Lifestyles collection."""
        raise DeprecationWarning(
            "`lifestyles` collection is deprecated in 'v3'.")
