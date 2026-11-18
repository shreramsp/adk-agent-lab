"""Pydantic schemas: the exact JSON shape each structured agent must return."""

from pydantic import BaseModel, Field


class ResearchIntent(BaseModel):
    industry: str = Field(description="Target industry, e.g. 'electric vehicles'")
    country: str = Field(description="Country the companies invest in, e.g. 'USA'")
    num_companies: int = Field(default=3, description="How many example companies to study (1-5)")


class Company(BaseModel):
    name: str
    home_country: str
    investment: str = Field(description="What they invested in, where, and when")
    source_url: str


class CompanyList(BaseModel):
    companies: list[Company]


class Pattern(BaseModel):
    name: str = Field(description="Short label, e.g. 'State incentive package announced'")
    description: str = Field(description="What the signal looks like and why it predicts investment")
    typical_lead_time: str = Field(description="How long before the investment it appeared, e.g. '6-12 months'")
    seen_in: list[str] = Field(description="Names of the companies that showed this signal")
    evidence_urls: list[str]


class PatternReport(BaseModel):
    patterns: list[Pattern]
    summary: str = Field(description="2-3 sentence takeaway for a sales team")


class Lead(BaseModel):
    name: str
    home_country: str
    why_candidate: str
    source_url: str


class LeadList(BaseModel):
    leads: list[Lead]


class ScoredLead(BaseModel):
    name: str
    home_country: str
    score: int = Field(description="1 (weak) to 10 (very likely to invest soon)")
    matched_patterns: list[str]
    key_evidence: str = Field(description="1-2 sentences on the strongest signals")
    source_urls: list[str]


class LeadReport(BaseModel):
    leads: list[ScoredLead] = Field(description="Only VALID leads, sorted by score, highest first")
    summary: str = Field(description="2-3 sentence recommendation for a sales team")
