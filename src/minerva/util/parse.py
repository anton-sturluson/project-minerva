"""HTML and SEC filing parsing utilities."""

import re
from typing import Dict, Optional
from bs4 import BeautifulSoup


def extract_sec_document(file_path: str) -> str:
    """
    Extract HTML content from SEC filing wrapper.

    Args:
        file_path: Path to SEC filing text file

    Returns:
        HTML content from the document
    """
    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()

    # Extract content between <DOCUMENT> and </DOCUMENT>
    doc_match = re.search(r'<DOCUMENT>(.*?)</DOCUMENT>', content, re.DOTALL)
    if doc_match:
        doc_content = doc_match.group(1)

        # Find the actual HTML start
        html_match = re.search(r'(<html.*?>.*)', doc_content, re.DOTALL | re.IGNORECASE)
        if html_match:
            return html_match.group(1)

        return doc_content

    # If no DOCUMENT tags, assume it's already HTML
    return content


def parse_sec_header(file_path: str) -> Dict[str, str]:
    """
    Extract metadata from SEC filing header.

    Args:
        file_path: Path to SEC filing text file

    Returns:
        Dictionary with SEC filing metadata
    """
    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()

    metadata = {}

    # Extract header section
    header_match = re.search(r'<SEC-HEADER>(.*?)</SEC-HEADER>', content, re.DOTALL)
    if not header_match:
        return metadata

    header = header_match.group(1)

    # Extract key fields
    patterns = {
        'accession_number': r'ACCESSION NUMBER:\s+(\S+)',
        'submission_type': r'CONFORMED SUBMISSION TYPE:\s+(\S+)',
        'filing_date': r'FILED AS OF DATE:\s+(\d+)',
        'company_name': r'COMPANY CONFORMED NAME:\s+(.+?)$',
        'cik': r'CENTRAL INDEX KEY:\s+(\d+)',
        'period_of_report': r'CONFORMED PERIOD OF REPORT:\s+(\d+)',
    }

    for key, pattern in patterns.items():
        match = re.search(pattern, header, re.MULTILINE)
        if match:
            metadata[key] = match.group(1).strip()

    return metadata


def html_to_text(html_content: str, clean: bool = True) -> str:
    """
    Parse HTML and extract text content.

    Args:
        html_content: HTML string to parse
        clean: Whether to clean up whitespace and remove empty lines

    Returns:
        Extracted text content
    """
    soup = BeautifulSoup(html_content, 'lxml')

    # Remove script, style, and other non-content elements
    for element in soup(['script', 'style', 'meta', 'link']):
        element.decompose()

    # Get text
    text = soup.get_text(separator='\n')

    if clean:
        # Clean up excessive whitespace
        lines = (line.strip() for line in text.splitlines())
        text = '\n'.join(line for line in lines if line)

        # Reduce multiple blank lines to single blank line
        text = re.sub(r'\n{3,}', '\n\n', text)

    return text


def extract_sec_sections(html_content: str) -> Dict[str, str]:
    """
    Extract major sections from SEC 10-K filing.

    Common sections in 10-K:
    - Item 1: Business
    - Item 1A: Risk Factors
    - Item 7: Management's Discussion and Analysis
    - Item 8: Financial Statements
    - etc.

    Args:
        html_content: HTML content of the filing

    Returns:
        Dictionary mapping section names to their content
    """
    soup = BeautifulSoup(html_content, 'lxml')
    sections = {}

    # Look for common section patterns
    # SEC filings often use specific formatting for item headers
    item_pattern = re.compile(r'item\s+(\d+[a-z]?)[:\.\s]+(.+?)(?:\n|$)', re.IGNORECASE)

    text = soup.get_text()

    # Find all item headers
    matches = list(item_pattern.finditer(text))

    for i, match in enumerate(matches):
        item_num = match.group(1).upper()
        item_title = match.group(2).strip()
        section_name = f"Item {item_num}: {item_title}"

        # Extract content between this item and the next
        start_pos = match.end()
        end_pos = matches[i + 1].start() if i + 1 < len(matches) else len(text)

        content = text[start_pos:end_pos].strip()
        sections[section_name] = content

    return sections


def parse_sec_filing(file_path: str) -> Dict[str, any]:
    """
    Parse SEC filing and extract all relevant information.

    Args:
        file_path: Path to SEC filing text file

    Returns:
        Dictionary containing:
        - metadata: Filing metadata from header
        - html: Raw HTML content
        - text: Plain text content
        - sections: Major sections (if identifiable)
    """
    metadata = parse_sec_header(file_path)
    html_content = extract_sec_document(file_path)
    text_content = html_to_text(html_content)
    sections = extract_sec_sections(html_content)

    return {
        'metadata': metadata,
        'html': html_content,
        'text': text_content,
        'sections': sections,
    }
