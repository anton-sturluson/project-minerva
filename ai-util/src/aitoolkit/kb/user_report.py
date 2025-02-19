"""Module for dealing with user reports."""
from datetime import datetime, timedelta
from typing import Any

from bson.objectid import ObjectId
from pymongo.database import Database
from pymongo.cursor import Cursor


def get_unique_barcodes(db: Database) -> list[str]:
    """Return all unique barcodes in the database."""
    return db.reportversions.distinct("barcode")


def get_report_version(
    db: Database,
    barcode: str,
    get_latest: bool = True,
    report_version: int = -1,
    created_at: datetime | None = None,
    nth_version: int | None = None
) -> dict[str, Any] | None:
    """
    Get the report version object from mongo.

    Args:
        nth_version: Retrieve the nth report version. 
                     Positive values count from the start (0-indexed). 
                     Negative values count from the end (-1 is the last version).
    """
    query: dict[str, Any] = {"barcode": barcode}
    if isinstance(created_at, datetime):
        query["createdAt"] = {"$gte": created_at, "$lt": created_at + timedelta(days=1)}
    elif report_version > 0:
        query["report_version"] = report_version

    if get_latest:
        return db.reportversions.find_one(query, sort=[("report_version", -1)])
    if nth_version is not None:
        # Handle positive and negative indexing
        if nth_version >= 0:
            return (db.reportversions.find(query)
                    .sort("report_version", 1)
                    .skip(nth_version)
                    .limit(1)
                    .next())
        else:
            # For negative indexing, we need to count total documents first
            nth_version = abs(nth_version) - 1
            return (db.reportversions.find(query)
                    .sort("report_version", -1)
                    .skip(nth_version)
                    .limit(1)
                    .next())

    return db.reportversions.find_one(query)


def get_action_plan(
    db: Database,
    barcode: str | None = None,
    report_version_id: ObjectId | None = None
) -> dict[str, Any] | None:
    """Get the action plan from the report version."""
    if not report_version_id:
        report_version: dict[str, Any] | None = get_report_version(db, barcode)
        if not report_version:
            raise ValueError(f"Report version not found for barcode '{barcode}'")
        report_version_id = report_version["_id"]

    return db.reportactionplans.find_one({"report_version_id": report_version_id})


def get_health_concerns(
    db: Database,
    barcode: str | None = None,
    report_version_id: ObjectId | None = None,
    concern_ids: ObjectId | list[ObjectId] | None = None
) -> Cursor:
    """
    Get health concern(s) from the report version. A single or list of concern
    ids can be provided. If no report version id is provided, the latest report
    version will be fetched from the barcode.
    """
    if not report_version_id:
        report_version: dict[str, Any] | None = get_report_version(db, barcode)
        if not report_version:
            raise ValueError(f"Report version not found for barcode '{barcode}'")
        report_version_id = report_version["_id"]

    query = {"report_version_id": report_version_id}
    if concern_ids is not None:
        if isinstance(concern_ids, ObjectId):
            concern_ids = [concern_ids]
        query["kb_id"] = {"$in": concern_ids}

    return db.reporthealthconcerns.find(query)


def get_actions(
    db: Database,
    barcode: str | None = None,
    report_version_id: ObjectId | None = None,
    action_ids: ObjectId | list[ObjectId] | None = None
) -> Cursor:
    """Get the action from the report version."""
    if not report_version_id:
        report_version: dict[str, Any] | None = get_report_version(db, barcode)
        if not report_version:
            raise ValueError(f"Report version not found for barcode '{barcode}'")
        report_version_id = report_version["_id"]

    query = {"report_version_id": report_version_id}
    if action_ids is not None:
        if isinstance(action_ids, ObjectId):
            action_ids = [action_ids]
        query["kb_id"] = {"$in": action_ids}

    return db.reportactions.find(query)


def get_health_categories(
    db: Database,
    barcode: str | None = None,
    report_version_id: ObjectId | None = None
) -> Cursor:
    """Get the health concern from the report version."""
    if not report_version_id:
        report_version: dict[str, Any] | None = get_report_version(db, barcode)
        if not report_version:
            raise ValueError(f"Report version not found for barcode '{barcode}'")
        report_version_id = report_version["_id"]

    return db.reporthealthcategories.find({"report_version_id": report_version_id})


def get_food_digestions(
    db: Database,
    barcode: str | None = None,
    report_version_id: ObjectId | None = None,
    digestion_ids: ObjectId | list[ObjectId] | None = None
) -> Cursor:
    """Get the food digestion from the report version."""
    if not report_version_id:
        report_version: dict[str, Any] | None = get_report_version(db, barcode)
        if not report_version:
            raise ValueError(f"Report version not found for barcode '{barcode}'")
        report_version_id = report_version["_id"]

    query = {"report_version_id": report_version_id}
    if digestion_ids is not None:
        if isinstance(digestion_ids, ObjectId):
            digestion_ids = [digestion_ids]
        query["kb_id"] = {"$in": digestion_ids}

    return db.reportfooddigestions.find(query)
