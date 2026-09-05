"""Tenant isolation.

The rule: operational data belongs to exactly one tenant, and every query is
filtered automatically. The filter lives here — in one place — rather than being
repeated in each route, because a single forgotten `WHERE tenant_id = ...` is how
one customer ends up seeing another's bookings.

How it works:
  * `TenantMixin` adds the column to a model.
  * `current_tenant_id` is a context variable set per request from the logged-in
    user (see app/core/security.py).
  * A `do_orm_execute` listener injects the filter into every ORM SELECT.

Escape hatch: `with all_tenants():` runs a block unfiltered — used by platform
level code (migrations, the owner's cross-tenant views). It is deliberately
explicit so it shows up in review.
"""
from contextlib import contextmanager
from contextvars import ContextVar

from sqlalchemy import Integer, event, orm
from sqlalchemy.orm import Mapped, mapped_column, with_loader_criteria

from app.core.logging import get_logger

log = get_logger(__name__)

# None = not set (platform level); an int = that tenant's data only
current_tenant_id: ContextVar = ContextVar("current_tenant_id", default=None)
_bypass: ContextVar = ContextVar("tenant_bypass", default=False)

DEFAULT_TENANT_ID = 1


class TenantMixin:
    """Adds tenant ownership to a model."""
    tenant_id: Mapped[int] = mapped_column(
        Integer, default=DEFAULT_TENANT_ID, index=True, nullable=False)


def set_tenant(tenant_id):
    current_tenant_id.set(tenant_id)


def get_tenant():
    return current_tenant_id.get()


@contextmanager
def all_tenants():
    """Temporarily disable filtering (platform-level work only)."""
    token = _bypass.set(True)
    try:
        yield
    finally:
        _bypass.reset(token)


@contextmanager
def as_tenant(tenant_id):
    """Run a block as a specific tenant (background jobs, scripts)."""
    token = current_tenant_id.set(tenant_id)
    try:
        yield
    finally:
        current_tenant_id.reset(token)


def install(session_factory):
    """Attach the automatic filter to a Session class."""

    @event.listens_for(session_factory, "do_orm_execute")
    def _add_tenant_filter(state):
        if not state.is_select or state.is_column_load or state.is_relationship_load:
            return
        if _bypass.get():
            return
        tid = current_tenant_id.get()
        if tid is None:
            return          # platform context: no filtering
        state.statement = state.statement.options(
            with_loader_criteria(
                TenantMixin,
                lambda cls: cls.tenant_id == tid,
                include_aliases=True))


def stamp(obj):
    """Set tenant_id on a new object if the caller didn't."""
    tid = current_tenant_id.get()
    if tid is not None and getattr(obj, "tenant_id", None) in (None, 0):
        obj.tenant_id = tid
    return obj
