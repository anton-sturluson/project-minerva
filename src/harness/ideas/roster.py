"""The newsletter supplies identities only; its prose is never thesis evidence."""

import re
from datetime import date

from lxml import html
from pydantic import BaseModel, ConfigDict, Field


class Lead(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company: str = Field(min_length=1)
    fund: str = Field(min_length=1)
    symbol: str = ""


class Issue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str
    date: date
    roster: list[Lead] = Field(min_length=1)


def parse_roster(raw: str) -> list[Lead]:
    tree = html.fromstring(raw)
    for node in tree.xpath("//br"):
        node.tail = "\n" + (node.tail or "")
    for node in tree.xpath("//p | //li | //div"):
        node.tail = "\n" + (node.tail or "")
    text = tree.text_content()
    leads = []
    for body in re.findall(r"^\s*🔹\s*(.+)$", text, re.M):
        match = re.fullmatch(r"(.*?)\s+by\s+(.+)", body.strip())
        if not match:
            raise ValueError(f"Unrecognized roster entry: {body[:100]}")
        company, fund = match.groups()
        symbol = re.fullmatch(r"(.*?)\s*\(([^)]+)\)", company)
        leads.append(
            Lead(
                company=(symbol[1] if symbol else company).strip(),
                symbol=symbol[2].strip() if symbol else "",
                fund=fund.strip(),
            )
        )
    if not leads:
        raise ValueError("No newsletter roster found")
    return leads
