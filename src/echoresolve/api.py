from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from echoresolve import store
from echoresolve.llm_router import route_intent
from echoresolve.runtime import handle_borrower_turn


@asynccontextmanager
async def lifespan(app: FastAPI):
    store.initialize()
    yield


app = FastAPI(
    title="EchoResolve",
    description="Synthetic borrower workflow API",
    version="0.1.0",
    lifespan=lifespan,
)


class CommitmentRequest(BaseModel):
    account_id: str = Field(min_length=1, max_length=40)
    amount_cents: int = Field(gt=0, le=1000000)
    due_date: str
    idempotency_key: str = Field(min_length=8, max_length=100)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/borrowers/{borrower_id}/context")
def borrower_context(borrower_id: str):
    context = store.get_borrower_context(borrower_id)
    if context is None:
        raise HTTPException(status_code=404, detail="Borrower not found")
    return context


@app.post("/commitments")
def create_commitment(request: CommitmentRequest):
    result = store.record_commitment(
        account_id=request.account_id,
        amount_cents=request.amount_cents,
        due_date=request.due_date,
        idempotency_key=request.idempotency_key,
    )
    if not result["ok"]:
        raise HTTPException(status_code=422, detail=result["reason"])
    return result

class ProposalRequest(BaseModel):
    borrower_id: str = Field(min_length=1, max_length=40)
    amount_cents: int = Field(gt=0, le=1000000)
    due_date: str
    ttl_minutes: int = Field(default=10, ge=1, le=30)


class ProposalConfirmationRequest(BaseModel):
    borrower_id: str = Field(min_length=1, max_length=40)
    proposal_id: str = Field(min_length=36, max_length=36)


@app.post("/proposals")
def create_proposal(request: ProposalRequest):
    result = store.create_payment_proposal(
        borrower_id=request.borrower_id,
        amount_cents=request.amount_cents,
        due_date=request.due_date,
        ttl_minutes=request.ttl_minutes,
    )
    if not result["ok"]:
        raise HTTPException(status_code=422, detail=result["reason"])
    return result


@app.post("/proposals/confirm")
def confirm_proposal(request: ProposalConfirmationRequest):
    result = store.confirm_payment_proposal(
        borrower_id=request.borrower_id,
        proposal_id=request.proposal_id,
    )
    if not result["ok"]:
        raise HTTPException(status_code=422, detail=result["reason"])
    return result

class IntentRouteRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


@app.post("/agent/route")
def route_agent_intent(request: IntentRouteRequest):
    return route_intent(request.message)

class AgentTurnRequest(BaseModel):
    borrower_id: str = Field(min_length=1, max_length=40)
    message: str = Field(min_length=1, max_length=2000)


@app.post("/agent/turn")
def agent_turn(request: AgentTurnRequest):
    return handle_borrower_turn(request.borrower_id, request.message)
