"""MongoDB utilities."""
from pymongo import MongoClient
from pymongo.collection import Collection


client: MongoClient = MongoClient()
transcripts: Collection = client["transcripts"]
