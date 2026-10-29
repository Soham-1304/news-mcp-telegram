from abc import ABC, abstractmethod
from typing import List, Optional
from pydantic import BaseModel, Field


class Article(BaseModel):
    title: str = Field(..., description="Headline of the article")
    url: str = Field(..., description="Canonical URL to the article")
    source: str = Field(..., description="Publication source name, e.g. DeepLearning.AI, The Guardian")
    writer: str = Field(default="", description="Author or journalist name")
    topic: str = Field(default="Artificial Intelligence", description="Primary topic or category")
    published_at: str = Field(default="", description="ISO 8601 formatted publication timestamp")
    location: str = Field(default="", description="Geographic location or origin if available")
    summary: str = Field(default="", description="Concise synopsis or excerpt")
    full_content: Optional[str] = Field(default=None, description="Full cleaned body text if extracted")

    def to_dict(self) -> dict:
        return self.model_dump()


class BaseNewsSource(ABC):
    """Abstract base class for all news sources."""
    name: str

    @abstractmethod
    def fetch_articles(self, limit: int = 10) -> List[Article]:
        """Fetch and normalize articles from the source."""
        pass

