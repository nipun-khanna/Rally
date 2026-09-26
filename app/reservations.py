"""Idempotent local demo reservation service."""

from uuid import NAMESPACE_URL, uuid5

from app.models import Proposal, Reservation
from app.store import Store


def create_reservation(store: Store, proposal: Proposal) -> Reservation:
    existing = store.reservation(proposal.id)
    if existing:
        return existing
    confirmation = "RLY-" + uuid5(NAMESPACE_URL, proposal.id).hex[:8].upper()
    return store.save_reservation(Reservation(proposal.id, confirmation, "confirmed"))
