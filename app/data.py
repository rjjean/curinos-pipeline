"""
Seed Data for the Application Under Test.

Sythetic finacial accout records chosen to mirror regulated-domain data 
that Curinos works with. Uses seeded RNG so the same dataset is produced 
every run, essential for reconciliation tests.
"""
from __future__ import annotations
from datetime import date, timedelta
from typing import List, Dict, Any
import random

_TIERS = ["Platinum", "Gold", "Silver", "Bronze"]
_REGIONS = ["Northeast", "Southeast", "Midwest", "Southwest", "West"]
_PRODUCT_LINES = ["Savings", "Checking", "MMA", "CD", "IRA"]

def generate_records(n: int = 75, seed: int = 42) -> List[Dict[str, Any]]:
    """Generate a seeded RNG synthetic dataset of n account records."""
    rng = random.Random(seed)
    base_date = date(2024, 1, 1)

    records: List[Dict[str, Any]] = []
    for i in range(1, n + 1):
        days_offset = rng.randint(0, 800)
        records.append(
            {
                "id": i,
                "account_id": f"ACC-{i:05d}",
                "tier": rng.choice(_TIERS),
                "region": rng.choice(_REGIONS),
                "product_line": rng.choice(_PRODUCT_LINES),
                "balance": round(rng.uniform(100.00, 250_000.00), 2),
                "transaction_count": rng.randint(0, 500),
                "last_activity_date": (base_date + timedelta(days=days_offset)).isoformat(),
                "is_active": rng.random() > 0.1,
            }
        )
    return records


RECORDS: List[Dict[str, Any]] = generate_records()


