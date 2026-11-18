"""Bounded question, provider data and public curation result."""

from typing import Annotated
from unicodedata import category
from urllib.parse import urlsplit

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints

PUBLIC_ARTICLE_LIMIT = 50


def valid_text(value: str) -> str:
    if any(category(char) == "Cs" for char in value):
        raise ValueError("Invalid Unicode text")
    return value


def absolute_article_link(value: str) -> str:
    if "\\" in value or any(
        char.isspace() or category(char) in {"Cc", "Cf", "Cs"} for char in value
    ):
        raise ValueError("Invalid article URL")
    url = urlsplit(value)
    if (
        url.scheme not in {"http", "https"}
        or not url.hostname
        or url.username is not None
        or url.password is not None
        or "%" in url.netloc
        or url.port == 0
    ):
        raise ValueError("Invalid article URL")
    return value


class CurationDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    pergunta: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=2000),
        AfterValidator(valid_text),
    ]


Source = Annotated[str, Field(min_length=1, max_length=200), AfterValidator(valid_text)]
Category = Annotated[str, Field(min_length=1, max_length=80), AfterValidator(valid_text)]


class Article(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore", hide_input_in_errors=True)

    titulo: Annotated[str, Field(min_length=1, max_length=500), AfterValidator(valid_text)]
    link: Annotated[str, Field(max_length=2048), AfterValidator(absolute_article_link)]
    fonte: Source | None = None
    idioma: Annotated[str, Field(max_length=32), AfterValidator(valid_text)] | None = None
    data_publicacao: Annotated[str, Field(max_length=100), AfterValidator(valid_text)] | None = None


class CurationResult(BaseModel):
    enabled: bool
    artigos: list[Article] = Field(default_factory=list, max_length=PUBLIC_ARTICLE_LIMIT)
    total: int = 0
    categoria: Category = "geral"
    fontes_consultadas: list[Source] = Field(default_factory=list, max_length=50)
    fontes_indisponiveis: list[Source] = Field(default_factory=list, max_length=50)
    truncated: bool = False


class ProviderArticles(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore", hide_input_in_errors=True)

    artigos: list[Article] = Field(max_length=1000)
    categoria: Category = "geral"
    fontes_consultadas: list[Source] = Field(default_factory=list, max_length=50)
    fontes_indisponiveis: list[Source] = Field(default_factory=list, max_length=50)

    def public_result(self) -> CurationResult:
        total = len(self.artigos)
        return CurationResult(
            enabled=True,
            artigos=self.artigos[:PUBLIC_ARTICLE_LIMIT],
            total=total,
            categoria=self.categoria,
            fontes_consultadas=self.fontes_consultadas,
            fontes_indisponiveis=self.fontes_indisponiveis,
            truncated=total > PUBLIC_ARTICLE_LIMIT,
        )


class ProviderFeed(ProviderArticles):
    categoria: Category
    total: int = Field(ge=0)
