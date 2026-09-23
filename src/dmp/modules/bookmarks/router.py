"""User bookmarks (universities for now; any catalog item type fits).

A bookmark denormalizes the display fields (title/subtitle/icon/url) so the
panel renders without extra joins; `url` holds the SPA route (e.g. the
university slug). Clicking a bookmark navigates there.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_session
from ...deps import current_user_id
from ...domain.models import UserBookmark
from ...envelope import AppException, ok
from ...security import new_uuid_hex

router = APIRouter(prefix="/api/v1/client/bookmarks", tags=["bookmarks"])


class BookmarkRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    itemType: str = "university"
    itemId: str
    title: str
    subtitle: str | None = None
    url: str  # SPA route to open on click (e.g. university slug)


class BookmarkResponse(BaseModel):
    id: str
    itemType: str
    itemId: str
    title: str
    subtitle: str | None = None
    url: str
    createdAt: datetime | None = None


def _to_response(b: UserBookmark) -> dict:
    return BookmarkResponse(
        id=b.id,
        itemType=b.item_type,
        itemId=b.item_id,
        title=b.title,
        subtitle=b.subtitle,
        url=b.url,
        createdAt=b.created_at,
    ).model_dump(exclude_none=True)


@router.get("")
async def list_bookmarks(
    user_id: str = Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
):
    rows = (
        await session.execute(
            select(UserBookmark)
            .where(UserBookmark.user_id == user_id)
            .order_by(UserBookmark.created_at.desc())
        )
    ).scalars().all()
    return ok([_to_response(b) for b in rows])


@router.post("")
async def add_bookmark(
    req: BookmarkRequest,
    user_id: str = Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
):
    if not req.title.strip():
        raise AppException.validation("title is required")
    bookmark = UserBookmark(
        id=new_uuid_hex(),
        user_id=user_id,
        item_type=req.itemType[:32],
        item_id=req.itemId[:64],
        title=req.title.strip()[:200],
        subtitle=(req.subtitle or "").strip()[:200] or None,
        url=req.url.strip()[:300],
        created_at=datetime.now(UTC),
    )
    session.add(bookmark)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise AppException.conflict("Already bookmarked") from None
    return ok(_to_response(bookmark))


@router.delete("/{bookmark_id}")
async def remove_bookmark(
    bookmark_id: str,
    user_id: str = Depends(current_user_id),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        delete(UserBookmark).where(
            UserBookmark.id == bookmark_id, UserBookmark.user_id == user_id
        )
    )
    await session.commit()
    if result.rowcount == 0:
        raise AppException.not_found("Bookmark not found")
    return ok()
