from backend.app.literature.providers.acs_provider import AcsProvider
from backend.app.literature.providers.arxiv_provider import ArxivProvider
from backend.app.literature.providers.base import FulltextResult, LiteratureProvider, MarkdownResult, MetadataResult
from backend.app.literature.providers.crossref_provider import CrossrefProvider
from backend.app.literature.providers.elsevier_provider import ElsevierProvider
from backend.app.literature.providers.generic_html_provider import GenericHtmlProvider
from backend.app.literature.providers.pdf_provider import PdfProvider
from backend.app.literature.providers.pmc_provider import PmcProvider
from backend.app.literature.providers.pubmed_provider import PubmedProvider
from backend.app.literature.providers.unpaywall_provider import UnpaywallProvider

__all__ = [
    "AcsProvider",
    "ArxivProvider",
    "CrossrefProvider",
    "ElsevierProvider",
    "FulltextResult",
    "GenericHtmlProvider",
    "LiteratureProvider",
    "MarkdownResult",
    "MetadataResult",
    "PdfProvider",
    "PmcProvider",
    "PubmedProvider",
    "UnpaywallProvider",
]
