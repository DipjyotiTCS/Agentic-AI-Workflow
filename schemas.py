from pydantic import BaseModel, Field, conlist, confloat
from typing import List, Literal, Optional, Dict, Any

class AttachmentInfo(BaseModel):
    filename: str
    content_type: str
    size_bytes: int

class EmailInput(BaseModel):
    subject: str = Field(..., min_length=1, max_length=200)
    body: str = Field(..., min_length=10, max_length=20000)
    attachments: List[AttachmentInfo] = Field(default_factory=list)

class ClassificationResult(BaseModel):
    category: Literal["sales", "support", "unknown"]
    intent: Literal[
        "specific_product_query",
        "requirement_to_product_suggestion",
        "best_price_offer_or_bundling",
        "need_more_information",
        "other"
    ]
    confidence: confloat(ge=0.0, le=1.0)
    reasoning: str = Field(..., min_length=10, max_length=1000)

class ProductRecommendation(BaseModel):
    sku: str
    name: str
    purpose: str
    price_usd: float
    score: confloat(ge=0.0, le=1.0)
    reasoning: str = Field(..., min_length=10, max_length=800)

class BundleOption(BaseModel):
    name: str
    items: conlist(str, min_length=1, max_length=6)
    total_price_usd: float
    score: confloat(ge=0.0, le=1.0)
    reasoning: str = Field(..., min_length=10, max_length=800)

class SalesWorkflowResult(BaseModel):
    ticket_id: str
    message_to_rep: str
    recommendations: List[ProductRecommendation] = Field(default_factory=list)
    bundles: List[BundleOption] = Field(default_factory=list)
    follow_up_questions: List[str] = Field(default_factory=list)

class SupportWorkflowResult(BaseModel):
    ticket_id: str
    message_to_rep: str
    follow_up_questions: List[str] = Field(default_factory=list)

class FinalAgentResponse(BaseModel):
    category: str
    classification: ClassificationResult
    sales: Optional[SalesWorkflowResult] = None
    support: Optional[SupportWorkflowResult] = None
    raw_debug: Optional[Dict[str, Any]] = None
