"""Beneficiary ownership analysis: common owners and ownership chains."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select

from aml_monitoring.models import Account, Customer, RelationshipEdge


@dataclass
class Owner:
    """An entity (customer) that owns or controls multiple accounts."""

    customer_id: int
    customer_name: str
    country: str
    account_ids: list[int] = field(default_factory=list)


@dataclass
class OwnershipLink:
    """A link in an ownership chain."""

    account_id: int
    customer_id: int
    customer_name: str
    country: str
    link_type: str  # "direct" or "counterparty_pattern"
    shared_counterparties: list[str] = field(default_factory=list)


def find_common_owners(
    session: Any, account_ids: list[int]
) -> list[Owner]:
    """
    Find customers who own multiple accounts in the given set.

    Args:
        session: DB session.
        account_ids: List of account IDs to check.

    Returns:
        List of Owner objects (customers owning 2+ of the given accounts).
    """
    if len(account_ids) < 2:
        return []

    accounts = list(
        session.execute(
            select(Account, Customer)
            .join(Customer, Account.customer_id == Customer.id)
            .where(Account.id.in_(account_ids))
        ).all()
    )

    # Group by customer_id
    customer_accounts: dict[int, list[tuple[Account, Customer]]] = {}
    for acct, cust in accounts:
        customer_accounts.setdefault(cust.id, []).append((acct, cust))

    owners: list[Owner] = []
    for cust_id, acct_cust_pairs in customer_accounts.items():
        if len(acct_cust_pairs) < 2:
            continue
        _, cust = acct_cust_pairs[0]
        owners.append(
            Owner(
                customer_id=cust_id,
                customer_name=cust.name,
                country=cust.country,
                account_ids=[a.id for a, _ in acct_cust_pairs],
            )
        )

    return owners


def get_ownership_chain(
    session: Any, account_id: int
) -> list[OwnershipLink]:
    """
    Get the ownership chain for an account.

    Returns:
        - Direct owner (customer)
        - Accounts sharing counterparty patterns (possible same-entity control)
    """
    # Direct owner
    result = session.execute(
        select(Account, Customer)
        .join(Customer, Account.customer_id == Customer.id)
        .where(Account.id == account_id)
    ).first()

    if not result:
        return []

    acct, cust = result
    chain: list[OwnershipLink] = [
        OwnershipLink(
            account_id=acct.id,
            customer_id=cust.id,
            customer_name=cust.name,
            country=cust.country,
            link_type="direct",
        )
    ]

    # Find accounts sharing counterparties (potential same-entity control)
    my_cps = set(
        row[0]
        for row in session.execute(
            select(RelationshipEdge.dst_key).where(
                RelationshipEdge.src_type == "account",
                RelationshipEdge.src_id == account_id,
                RelationshipEdge.dst_type == "counterparty",
            )
        ).all()
    )

    if not my_cps:
        return chain

    # Other accounts sharing 2+ counterparties
    other_edges = list(
        session.execute(
            select(RelationshipEdge).where(
                RelationshipEdge.src_type == "account",
                RelationshipEdge.src_id != account_id,
                RelationshipEdge.dst_type == "counterparty",
                RelationshipEdge.dst_key.in_(my_cps),
            )
        )
        .scalars()
        .all()
    )

    acct_shared: dict[int, set[str]] = {}
    for edge in other_edges:
        acct_shared.setdefault(edge.src_id, set()).add(edge.dst_key)

    for other_acct_id, shared_cps in acct_shared.items():
        if len(shared_cps) < 2:
            continue

        other_result = session.execute(
            select(Account, Customer)
            .join(Customer, Account.customer_id == Customer.id)
            .where(Account.id == other_acct_id)
        ).first()

        if other_result:
            other_acct, other_cust = other_result
            chain.append(
                OwnershipLink(
                    account_id=other_acct.id,
                    customer_id=other_cust.id,
                    customer_name=other_cust.name,
                    country=other_cust.country,
                    link_type="counterparty_pattern",
                    shared_counterparties=sorted(shared_cps),
                )
            )

    return chain
