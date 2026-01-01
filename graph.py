from typing import TypedDict, List, Dict, Any, Optional
from langgraph.graph import StateGraph, END
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
import json

from schemas import (
    EmailInput, ClassificationResult, FinalAgentResponse,
    SalesWorkflowResult, SupportWorkflowResult,
    ProductRecommendation, BundleOption
)
from guardrails import basic_input_guardrails, validate_or_raise, clamp_confidence
import db

KB = {
    "sales": ["pricing", "quote", "discount", "bundle", "purchase", "buy", "trial", "demo", "renewal", "invoice"],
    "support": ["error", "bug", "issue", "not working", "down", "broken", "failed", "incident", "unable", "crash"],
    "intent_rules": {
        "specific_product_query": ["sku", "product code", "looking for", "is available", "availability"],
        "requirement_to_product_suggestion": ["recommend", "suggest", "best fit", "need a solution", "requirements"],
        "best_price_offer_or_bundling": ["bundle", "best price", "discount", "offer", "package"],
        "need_more_information": ["clarify", "need more info", "not sure", "details needed"]
    }
}

class AgentState(TypedDict):
    run_id: str
    email: Dict[str, Any]
    attachments_meta: List[Dict[str, Any]]
    status_events: List[Dict[str, Any]]
    classification: Optional[Dict[str, Any]]
    final: Optional[Dict[str, Any]]

def _emit(state: AgentState, step: str, message: str, progress: int) -> AgentState:
    state["status_events"].append({"step": step, "message": message, "progress": progress})
    return state

def build_graph() -> Any:
    print("calling gpt")
    llm = ChatOpenAI(model="gpt-4o", temperature=0.0, model_kwargs={"response_format": {"type": "json_object"}})
    print("called gpt")

    classify_prompt = ChatPromptTemplate.from_messages([
        ("system",
         "You are a strict email classifier for a sales/support organization. "
         "Return ONLY valid JSON that matches this schema:\n"
         "{"
         "\"category\": \"sales|support|unknown\", "
         "\"intent\": \"specific_product_query|requirement_to_product_suggestion|best_price_offer_or_bundling|need_more_information|other\", "
         "\"confidence\": number between 0 and 1, "
         "\"reasoning\": string"
         "}.\n"
         "Use the provided knowledge base hints, but rely on the email content."),
        ("user",
         "KNOWLEDGE BASE HINTS:\n{kb}\n\nEMAIL SUBJECT:\n{subject}\n\nEMAIL BODY:\n{body}\n")
    ])

    intent_prompt = ChatPromptTemplate.from_messages([
        ("system",
         "You extract intent details. Return ONLY valid JSON:\n"
         "{"
         "\"mentions\": [\"...\"], "
         "\"need_keywords\": [\"...\"], "
         "\"wants_bundles\": true|false, "
         "\"needs_more_info\": true|false, "
         "\"follow_up_questions\": [\"...\"], "
         "\"support_symptoms\": [\"...\"], "
         "\"environment_hints\": [\"...\"], "
         "\"urgency\": \"low|medium|high\""
         "}\n"
         "Keep arrays short (max 8 items)."),
        ("user",
         "EMAIL SUBJECT:\n{subject}\n\nEMAIL BODY:\n{body}\n\nCLASSIFICATION:\n{classification}\n")
    ])

    recommend_prompt = ChatPromptTemplate.from_messages([
        ("system",
         "You are a product recommendation engine. Return ONLY valid JSON array. "
         "Each item must have: sku, name, purpose, price_usd, score(0..1), reasoning. "
         "Rank best first. Provide 1-5 items."),
        ("user",
         "CUSTOMER NEEDS:\n{needs}\n\nAVAILABLE PRODUCTS:\n{products}\n")
    ])

    bundle_prompt = ChatPromptTemplate.from_messages([
        ("system",
         "You create bundle options. Return ONLY valid JSON array. "
         "Each item: name, items(array of SKUs or product names), total_price_usd, score(0..1), reasoning. "
         "Return exactly 5 items."),
        ("user",
         "CUSTOMER CONTEXT:\n{context}\n\nAVAILABLE ACTIVE PRODUCTS:\n{products}\n"
         "Bundling guidance: keep bundles realistic and price-sensitive.")
    ])

    def node_validate_input(state: AgentState) -> AgentState:
        _emit(state, "validate", "Validating input and attachments...", 5)
        email = EmailInput.model_validate(state["email"])
        basic_input_guardrails(email.body)
        state["email"] = email.model_dump()
        return _emit(state, "validate", "Input validated.", 10)

    def node_classify(state: AgentState) -> AgentState:
        _emit(state, "classify", "Classifying email (sales vs support) and intent...", 20)
        email = state["email"]
        msg = llm.invoke(classify_prompt.format_messages(
            kb=json.dumps(KB, ensure_ascii=False),
            subject=email["subject"],
            body=email["body"]
        ))
        data = json.loads(msg.content)
        data["confidence"] = clamp_confidence(data.get("confidence", 0.0))
        cls = validate_or_raise(ClassificationResult, data)
        state["classification"] = cls.model_dump()
        return _emit(state, "classify", f"Classified as {cls.category} ({cls.intent}).", 35)

    def route_category(state: AgentState) -> str:
        c = (state.get("classification") or {}).get("category", "unknown")
        if c == "sales":
            return "sales_workflow"
        if c == "support":
            return "support_workflow"
        return "unknown_workflow"

    def node_sales_workflow(state: AgentState) -> AgentState:
        _emit(state, "sales", "Starting sales workflow: logging ticket...", 45)
        email = state["email"]
        cls = state["classification"]

        ticket_id = db.create_sales_ticket(
            email_subject=email["subject"],
            email_body=email["body"],
            attachments=state["attachments_meta"],
            classification=cls,
            customer_hint=None
        )
        _emit(state, "sales", f"Sales ticket created: {ticket_id}", 55)

        _emit(state, "sales", "Extracting intent details from email...", 60)
        msg = llm.invoke(intent_prompt.format_messages(
            subject=email["subject"],
            body=email["body"],
            classification=json.dumps(cls, ensure_ascii=False)
        ))
        details = json.loads(msg.content)
        mentions = (details.get("mentions") or [])[:8]
        need_keywords = (details.get("need_keywords") or [])[:8]
        wants_bundles = bool(details.get("wants_bundles"))
        needs_more_info = bool(details.get("needs_more_info"))
        follow_up_questions = (details.get("follow_up_questions") or [])[:6]

        intent = cls.get("intent", "other")
        recs: List[ProductRecommendation] = []
        bundles: List[BundleOption] = []
        rep_message = ""

        if intent == "specific_product_query":
            _emit(state, "sales", "Searching product database for mentioned products...", 70)
            found = db.search_products_by_exact_mention(mentions)
            if not found:
                rep_message = (
                    f"Ticket {ticket_id} logged. The mentioned product was not found in the product database. "
                    "It may be discontinued or named differently."
                )
            else:
                active_found = [p for p in found if p["is_active"] == 1]
                inactive_found = [p for p in found if p["is_active"] == 0]
                if active_found:
                    msg2 = llm.invoke(recommend_prompt.format_messages(
                        needs="Customer asked for specific product(s). Recommend the closest match from the list.",
                        products=json.dumps(active_found, ensure_ascii=False)
                    ))
                    arr = json.loads(msg2.content)
                    for item in arr[:5]:
                        item["score"] = clamp_confidence(item.get("score", 0.0))
                        recs.append(ProductRecommendation.model_validate(item))
                    rep_message = f"Ticket {ticket_id} logged. Found matching product(s) for the customer."
                else:
                    rep_message = f"Ticket {ticket_id} logged. The mentioned product appears to be no longer available."
                    if inactive_found:
                        rep_message += " Consider proposing active alternatives."

        elif intent == "requirement_to_product_suggestion":
            _emit(state, "sales", "Interpreting requirements and finding suitable products...", 70)
            candidates = db.search_products_by_need_keywords(need_keywords, limit=10)
            active = [p for p in candidates if p["is_active"] == 1] or db.get_active_products()
            msg2 = llm.invoke(recommend_prompt.format_messages(
                needs=json.dumps({"need_keywords": need_keywords, "subject": email["subject"]}, ensure_ascii=False),
                products=json.dumps(active, ensure_ascii=False)
            ))
            arr = json.loads(msg2.content)
            for item in arr[:5]:
                item["score"] = clamp_confidence(item.get("score", 0.0))
                recs.append(ProductRecommendation.model_validate(item))
            rep_message = f"Ticket {ticket_id} logged. Suggested multiple product options at different price points."

        elif intent == "best_price_offer_or_bundling" or wants_bundles:
            _emit(state, "sales", "Creating bundle options and best price offers...", 70)
            active = db.get_active_products()
            msg2 = llm.invoke(bundle_prompt.format_messages(
                context=json.dumps({"need_keywords": need_keywords, "mentions": mentions}, ensure_ascii=False),
                products=json.dumps(active, ensure_ascii=False),
            ))
            arr = json.loads(msg2.content)
            for item in arr[:5]:
                item["score"] = clamp_confidence(item.get("score", 0.0))
                bundles.append(BundleOption.model_validate(item))
            bundles.sort(key=lambda b: b.total_price_usd)
            rep_message = f"Ticket {ticket_id} logged. Generated 5 bundle options sorted by price."

        else:
            needs_more_info = True

        if needs_more_info:
            _emit(state, "sales", "Need more information to proceed accurately.", 78)
            if not follow_up_questions:
                follow_up_questions = [
                    "Which product category are you most interested in (CRM, Support Desk, Analytics, etc.)?",
                    "How many users/seats do you need and what is your target budget range?",
                    "Are there must-have features (SLA, automation, dashboards, integrations)?",
                ]
            rep_message = f"Ticket {ticket_id} logged, but more information is required to proceed."

        result = SalesWorkflowResult(
            ticket_id=ticket_id,
            message_to_rep=rep_message,
            recommendations=recs,
            bundles=bundles,
            follow_up_questions=follow_up_questions
        )

        _emit(state, "sales", "Validating output against guardrails...", 88)
        validate_or_raise(SalesWorkflowResult, result.model_dump())

        final = FinalAgentResponse(
            category="sales",
            classification=ClassificationResult.model_validate(cls),
            sales=result
        )
        state["final"] = final.model_dump()
        return _emit(state, "sales", "Sales workflow complete.", 95)

    def node_support_workflow(state: AgentState) -> AgentState:
        _emit(state, "support", "Starting support workflow: logging ticket...", 45)
        email = state["email"]
        cls = state["classification"] or {}

        ticket_id = db.create_support_ticket(
            email_subject=email["subject"],
            email_body=email["body"],
            attachments=state["attachments_meta"],
            intent=str(cls.get("intent", "other")),
            confidence=float(cls.get("confidence", 0.0) or 0.0),
            classification=cls,
            customer_hint=None
        )
        _emit(state, "support", f"Support ticket created: {ticket_id}", 55)

        _emit(state, "support", "Extracting troubleshooting context and follow-up questions...", 65)
        msg = llm.invoke(intent_prompt.format_messages(
            subject=email["subject"],
            body=email["body"],
            classification=json.dumps(cls, ensure_ascii=False)
        ))
        details = json.loads(msg.content)
        follow_up_questions = (details.get("follow_up_questions") or [])[:6]
        symptoms = (details.get("support_symptoms") or [])[:8]
        env = (details.get("environment_hints") or [])[:8]
        urgency = details.get("urgency") or "medium"

        if not follow_up_questions:
            follow_up_questions = [
                "What exact error message(s) do you see (copy/paste if possible)?",
                "When did the issue start and is it intermittent or constant?",
                "How many users are affected and what is the business impact?",
                "What environment is impacted (prod/stage), and what region?",
                "Steps to reproduce (if known) and screenshots/log snippets?",
            ]

        msg_to_rep = (
            f"Ticket {ticket_id} logged. Support request detected (urgency: {urgency}). "
            "Collect the details below and route to the support team/runbook."
        )
        if symptoms:
            msg_to_rep += f"\n\nObserved symptoms (extracted): {', '.join(symptoms)}"
        if env:
            msg_to_rep += f"\nEnvironment hints (extracted): {', '.join(env)}"

        result = SupportWorkflowResult(
            ticket_id=ticket_id,
            message_to_rep=msg_to_rep,
            follow_up_questions=follow_up_questions
        )

        _emit(state, "support", "Validating output against guardrails...", 88)
        validate_or_raise(SupportWorkflowResult, result.model_dump())

        final = FinalAgentResponse(
            category="support",
            classification=ClassificationResult.model_validate(cls),
            support=result
        )
        state["final"] = final.model_dump()
        return _emit(state, "support", "Support workflow complete.", 95)

    def node_unknown_workflow(state: AgentState) -> AgentState:
        _emit(state, "unknown", "Unable to confidently classify. Asking for more information...", 60)
        cls = state["classification"] or {
            "category": "unknown",
            "intent": "need_more_information",
            "confidence": 0.2,
            "reasoning": "Insufficient signal."
        }
        cls = ClassificationResult.model_validate(cls)
        final = FinalAgentResponse(
            category="unknown",
            classification=cls,
            support=SupportWorkflowResult(
                ticket_id="",
                message_to_rep="I couldn't confidently determine if this is sales or support. Please clarify.",
                follow_up_questions=[
                    "Is the customer asking about pricing/purchase (sales) or a problem/bug (support)?",
                    "What outcome does the customer want from this email?"
                ]
            )
        )
        state["final"] = final.model_dump()
        return _emit(state, "unknown", "Done.", 95)

    def node_finalize(state: AgentState) -> AgentState:
        _emit(state, "finalize", "Finalizing response...", 99)
        validate_or_raise(FinalAgentResponse, state["final"])
        return _emit(state, "finalize", "Completed.", 100)

    g = StateGraph(AgentState)
    g.add_node("validate_input", node_validate_input)
    g.add_node("classify", node_classify)
    g.add_node("sales_workflow", node_sales_workflow)
    g.add_node("support_workflow", node_support_workflow)
    g.add_node("unknown_workflow", node_unknown_workflow)
    g.add_node("finalize", node_finalize)

    g.set_entry_point("validate_input")
    g.add_edge("validate_input", "classify")
    g.add_conditional_edges("classify", route_category, {
        "sales_workflow": "sales_workflow",
        "support_workflow": "support_workflow",
        "unknown_workflow": "unknown_workflow",
    })
    g.add_edge("sales_workflow", "finalize")
    g.add_edge("support_workflow", "finalize")
    g.add_edge("unknown_workflow", "finalize")
    g.add_edge("finalize", END)

    return g.compile()
