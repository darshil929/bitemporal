"""What needs a signed-in person's attention."""

from fastapi import APIRouter, Depends, status

from api.dependencies import DatabaseDependency, SignedInDependency, signed_in
from api.routers.market import MARKET_READ_RESPONSES
from api.schemas.attention_feed import AttentionResponse
from api.schemas.sessions import NotSignedInResponse
from api.services import attention_feed

router = APIRouter(
    prefix="/attention",
    tags=["attention"],
    dependencies=[Depends(signed_in)],
    responses={status.HTTP_401_UNAUTHORIZED: {"model": NotSignedInResponse}},
)


@router.get("", responses=MARKET_READ_RESPONSES)
async def needs_attention(
    user: SignedInDependency, database: DatabaseDependency
) -> AttentionResponse:
    """The person's alerts the newest session triggered, the venues whose session on the published
    day failed its checks, and, among the instruments the person's watchlists hold, divergences,
    replaced ISINs and unadjusted corporate actions within a month's sessions."""
    found = await attention_feed.attention_feed(database, user.id)
    return AttentionResponse.model_validate(found)
