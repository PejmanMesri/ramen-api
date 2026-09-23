"""Idempotent startup seeder.

Runs on every boot (lifespan). Failures are logged, never fatal — parity with DbSeeder.
Seeds: default super-admin (syncs password from env), the `university` catalog type,
~195 countries, two subscription plans, and the sample universities from sample-data/.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import security
from ..config import get_settings
from ..db import utcnow
from ..domain.enums import AdminRole
from ..domain.models import (
    Admin,
    CatalogItemType,
    Country,
    SubscriptionPlan,
)
from .country_seed import COUNTRIES, flag_from_code

log = logging.getLogger("dmp.seed")


async def seed_all(session: AsyncSession) -> None:
    try:
        await seed_admin(session)
        await seed_catalog_type(session)
        await seed_countries(session)
        await seed_plans(session)
        await seed_sample_universities(session)
        # Only import the university_data dump into a fresh catalog — with a
        # large restored dump (2.8k+ rows) this would re-refresh on every boot.
        from sqlalchemy import func, select

        from ..domain.models import University

        count = (await session.execute(select(func.count(University.id)))).scalar_one()
        if count < 50:
            await import_university_data(session)
        await seed_demo_subscriptions(session)
    except Exception:
        log.exception("[Seed] seeding failed — startup continues.")


async def seed_demo_subscriptions(session: AsyncSession) -> None:
    """Demo users + subscriptions + payments so the admin panel has data to show.
    Idempotent: skipped entirely once the demo users exist."""
    from datetime import timedelta

    from .. import security
    from ..domain.enums import PaymentStatus, SubscriptionStatus, UserStatus
    from ..domain.models import Payment, Subscription, SubscriptionPlan, User

    existing = (
        await session.execute(select(User).where(User.username == "demo_alice"))
    ).scalar_one_or_none()
    if existing is not None:
        return

    plans = {
        p.name_key: p
        for p in (
            await session.execute(select(SubscriptionPlan))
        ).scalars().all()
    }
    monthly = plans.get("plan.monthly.name")
    yearly = plans.get("plan.yearly.name")
    if monthly is None:
        log.warning("[Seed] No monthly plan found — skipping demo subscriptions.")
        return

    now = utcnow()

    def _user(uname: str, first: str, last: str) -> User:
        return User(
            id=security.new_uuid_hex(),
            username=uname,
            email=f"{uname}@example.com",
            password_hash=security.hash_password("Password123"),
            first_name=first,
            last_name=last,
            email_verified=True,
            status=UserStatus.Active,
        )

    alice = _user("demo_alice", "Alice", "Demo")
    bob = _user("demo_bob", "Bob", "Demo")
    carol = _user("demo_carol", "Carol", "Demo")
    session.add_all([alice, bob, carol])

    def _sub(user: User, plan: SubscriptionPlan, start_offset_days: int, status: SubscriptionStatus) -> Subscription:
        start = now - timedelta(days=start_offset_days)
        return Subscription(
            id=security.new_uuid_hex(),
            user_id=user.id,
            plan_id=plan.id,
            start_at=start,
            end_at=start + timedelta(days=plan.duration_days),
            status=status,
        )

    # alice: active monthly; bob: expired monthly; carol: active yearly (+ a pending payment).
    subs = [
        _sub(alice, monthly, 5, SubscriptionStatus.Active),
        _sub(bob, monthly, 60, SubscriptionStatus.Expired),
        _sub(carol, (yearly or monthly), 10, SubscriptionStatus.Active),
    ]
    session.add_all(subs)

    def _pay(user: User, sub: Subscription, plan: SubscriptionPlan, status: PaymentStatus, offset_days: int) -> Payment:
        return Payment(
            id=security.new_uuid_hex(),
            user_id=user.id,
            subscription_id=sub.id,
            plan_id=plan.id,
            amount_toman=plan.price_toman,
            status=status,
            gateway="zarinpal" if status != PaymentStatus.Succeeded else "manual",
            description=f"Demo: {plan.name_key} ({plan.duration_days} days)",
            paid_at=(now - timedelta(days=offset_days)) if status == PaymentStatus.Succeeded else None,
        )

    session.add_all(
        [
            _pay(alice, subs[0], monthly, PaymentStatus.Succeeded, 5),
            _pay(bob, subs[1], monthly, PaymentStatus.Succeeded, 60),
            _pay(carol, subs[2], (yearly or monthly), PaymentStatus.Succeeded, 10),
        ]
    )

    await session.commit()
    log.info("[Seed] Seeded 3 demo users with subscriptions and payments.")


async def import_university_data(session: AsyncSession) -> None:
    """Import rows from the restored `university_data` landing table (if any) into
    the canonical catalog. Merge-fill, idempotent — safe on every boot."""
    from ..modules.catalog.service import CatalogService

    catalog = CatalogService()
    summary = await catalog.import_university_data(session)
    if summary.get("totalRows"):
        log.info(
            "[Seed] university_data import: %s created, %s merged, %s skipped.",
            summary.get("created"),
            summary.get("merged"),
            summary.get("skipped"),
        )


async def seed_admin(session: AsyncSession) -> None:
    settings = get_settings()
    if not settings.auto_create_default_admin:
        return
    if not (settings.admin_username and settings.admin_password):
        log.warning("[Seed] Admin username/password not configured — skipping.")
        return

    admin = (
        await session.execute(select(Admin).where(Admin.username == settings.admin_username))
    ).scalar_one_or_none()

    if admin is None:
        session.add(
            Admin(
                id=security.new_uuid_hex(),
                username=settings.admin_username,
                password_hash=security.hash_password(settings.admin_password),
                first_name="Super",
                last_name="Admin",
                role=AdminRole.SuperAdmin,
                is_active=True,
            )
        )
        await session.commit()
        log.info("[Seed] Default super-admin '%s' created.", settings.admin_username)
    elif not security.verify_password(settings.admin_password, admin.password_hash):
        admin.password_hash = security.hash_password(settings.admin_password)
        await session.commit()
        log.info("[Seed] Default admin '%s' password synced from environment.", settings.admin_username)


async def seed_catalog_type(session: AsyncSession) -> None:
    existing = (
        await session.execute(select(CatalogItemType).where(CatalogItemType.code == "university"))
    ).scalar_one_or_none()
    if existing:
        return
    session.add(CatalogItemType(id=security.new_uuid_hex(), code="university", name_key="catalog.type.university"))
    await session.commit()


async def seed_countries(session: AsyncSession) -> None:
    any_country = (await session.execute(select(Country).limit(1))).scalar_one_or_none()
    if any_country:
        return
    rows = [
        Country(id=security.new_uuid_hex(), code=code, name=name, flag_emoji=flag_from_code(code))
        for code, name in COUNTRIES
    ]
    session.add_all(rows)
    await session.commit()
    log.info("[Seed] Seeded %d countries.", len(rows))


DEFAULT_PLANS = [
    # ── Gold tier ────────────────────────────────────────────────────────────
    {"name_key": "plan.gold.14d", "name": "Gold · 14 days", "description": "Gold: full university catalog, details and applications for two weeks.", "currency": "IRR", "price": 300_000, "duration_days": 14, "sort_order": 10, "features": {"tier": "gold"}},
    {"name_key": "plan.gold.1m", "name": "Gold · 1 month", "description": "Gold: full university catalog, details and applications for a month.", "currency": "IRR", "price": 500_000, "duration_days": 30, "sort_order": 11, "features": {"tier": "gold"}},
    {"name_key": "plan.gold.3m", "name": "Gold · 3 months", "description": "Gold: full university catalog, details and applications for three months.", "currency": "IRR", "price": 1_200_000, "duration_days": 90, "sort_order": 12, "features": {"tier": "gold"}},
    {"name_key": "plan.gold.6m", "name": "Gold · 6 months", "description": "Gold: full university catalog, details and applications for six months.", "currency": "IRR", "price": 2_000_000, "duration_days": 180, "sort_order": 13, "features": {"tier": "gold"}},
    {"name_key": "plan.gold.1y", "name": "Gold · 1 year", "description": "Gold: full university catalog, details and applications for a year.", "currency": "IRR", "price": 3_500_000, "duration_days": 365, "sort_order": 14, "features": {"tier": "gold"}},
    # ── Platinum tier ────────────────────────────────────────────────────────
    {"name_key": "plan.platinum.14d", "name": "Platinum · 14 days", "description": "Platinum: everything in Gold plus professors CRM and scholarships for two weeks.", "currency": "IRR", "price": 600_000, "duration_days": 14, "sort_order": 20, "features": {"tier": "platinum"}},
    {"name_key": "plan.platinum.1m", "name": "Platinum · 1 month", "description": "Platinum: everything in Gold plus professors CRM and scholarships for a month.", "currency": "IRR", "price": 1_000_000, "duration_days": 30, "sort_order": 21, "features": {"tier": "platinum"}},
    {"name_key": "plan.platinum.3m", "name": "Platinum · 3 months", "description": "Platinum: everything in Gold plus professors CRM and scholarships for three months.", "currency": "IRR", "price": 2_500_000, "duration_days": 90, "sort_order": 22, "features": {"tier": "platinum"}},
    {"name_key": "plan.platinum.6m", "name": "Platinum · 6 months", "description": "Platinum: everything in Gold plus professors CRM and scholarships for six months.", "currency": "IRR", "price": 4_500_000, "duration_days": 180, "sort_order": 23, "features": {"tier": "platinum"}},
    {"name_key": "plan.platinum.1y", "name": "Platinum · 1 year", "description": "Platinum: everything in Gold plus professors CRM and scholarships for a year.", "currency": "IRR", "price": 8_000_000, "duration_days": 365, "sort_order": 24, "features": {"tier": "platinum"}},
]

# Legacy single-duration plans retired by the tier grid.
LEGACY_PLAN_KEYS = ["plan.monthly.name", "plan.yearly.name"]


async def seed_plans(session: AsyncSession) -> None:
    """Upsert the tier plan grid: create missing plans (fresh machine) and
    backfill display fields on existing rows. Legacy single-duration plans
    (monthly/yearly) are deactivated. Runs on every boot; idempotent."""
    changed = 0
    for spec in DEFAULT_PLANS:
        plan = (
            await session.execute(select(SubscriptionPlan).where(SubscriptionPlan.name_key == spec["name_key"]))
        ).scalar_one_or_none()
        if plan is None:
            session.add(
                SubscriptionPlan(
                    id=security.new_uuid_hex(),
                    name_key=spec["name_key"],
                    description_key=spec.get("description_key"),
                    name=spec["name"],
                    description=spec["description"],
                    currency=spec["currency"],
                    price_toman=spec["price"],
                    duration_days=spec["duration_days"],
                    is_active=True,
                    sort_order=spec["sort_order"],
                    features=spec["features"],
                )
            )
            changed += 1
        else:
            # Backfill display fields / currency only when empty (never clobber admin edits).
            if not plan.name:
                plan.name = spec["name"]
                changed += 1
            if not plan.description:
                plan.description = spec["description"]
                changed += 1
            if not plan.currency:
                # Row predates the Rials switch — set currency AND reprice to the
                # Rials default (the old Toman value would read as a odd Rials amount).
                plan.currency = spec["currency"]
                plan.price_toman = spec["price"]
                changed += 1

    # Retire legacy single-duration plans (admin may still see history).
    for legacy_key in LEGACY_PLAN_KEYS:
        legacy = (
            await session.execute(select(SubscriptionPlan).where(SubscriptionPlan.name_key == legacy_key))
        ).scalar_one_or_none()
        if legacy is not None and legacy.is_active:
            legacy.is_active = False
            changed += 1

    if changed:
        await session.commit()
        log.info("[Seed] Default subscription plans ensured (%d change/s).", changed)


async def seed_sample_universities(session: AsyncSession) -> None:
    # Any university present → skip (parity with the .NET seeder).
    from ..domain.models import University
    from ..modules.catalog.service import CatalogService

    any_uni = (await session.execute(select(University).limit(1))).scalar_one_or_none()
    if any_uni:
        return

    data_dir = _resolve_sample_data_dir()
    if not data_dir or not data_dir.is_dir():
        log.warning("[Seed] sample-data directory not found — skipping sample universities.")
        return

    catalog = CatalogService()
    order = 0
    for file in sorted(data_dir.glob("*_combined.json")):
        try:
            text = file.read_text(encoding="utf-8")
            source_name = file.stem.replace("_combined", "").strip()
            results = await catalog.import_json(session, text, source_name=source_name, country_code="US")
            for r in results:
                uni = (
                    await session.execute(select(University).where(University.id == r["universityId"]))
                ).scalar_one_or_none()
                if uni is not None:
                    uni.sort_order = order
                    order += 1
            await session.commit()
            log.info("[Seed] Imported %d university/ies from %s.", len(results), file.name)
        except Exception:
            log.exception("[Seed] Could not import %s.", file.name)


def _resolve_sample_data_dir() -> Path | None:
    """Locate the sample-data folder by walking up from CWD/base dir."""
    env_dir = os.environ.get("SAMPLE_DATA_DIR")
    if env_dir:
        p = Path(env_dir)
        return p if p.is_dir() else None

    # Walk up from CWD (covers local `uvicorn` + in-container /app).
    cwd = Path.cwd()
    for base in [cwd, *cwd.parents]:
        candidate = base / "sample-data"
        if candidate.is_dir():
            return candidate
    return None
