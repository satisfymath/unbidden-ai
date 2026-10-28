"""Seed a mealie with the shopping lists of a large household, through its API, as the protocol fixes it.

    uv run python -m bench.mealie_seed http://127.0.0.1:9092 --user changeme@example.com --password-env MEALIE_SEED_PW

50 lists x 100 items (5,000) over 580 foods, 80 % of the items checked off, as in D-036. Each list uses 100 distinct
foods, so mealie never merges two items into one. Deterministic (seed 20261028). Prints the counts mealie reports
afterwards; the run is invalid if they differ from what was asked.
"""

from __future__ import annotations

import argparse
import json
import os
import random

import httpx

FOODS, LISTS, ITEMS, CHECKED, SEED = 580, 50, 100, 0.8, 20261028


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("base")
    parser.add_argument("--user", required=True)
    parser.add_argument("--password-env", required=True)
    args = parser.parse_args()
    rng = random.Random(SEED)
    with httpx.Client(base_url=args.base, timeout=60) as client:
        token = (
            client.post("/api/auth/token", data={"username": args.user, "password": os.environ[args.password_env]})
            .raise_for_status()
            .json()["access_token"]
        )
        client.headers["Authorization"] = f"Bearer {token}"
        foods = [
            client.post("/api/foods", json={"name": f"unbidden-food-{i:03d}"}).raise_for_status().json()["id"]
            for i in range(FOODS)
        ]
        for j in range(LISTS):
            shopping = client.post("/api/households/shopping/lists", json={"name": f"unbidden-list-{j:02d}"})
            list_id = shopping.raise_for_status().json()["id"]
            chosen = rng.sample(foods, ITEMS)
            items = [
                {"shopping_list_id": list_id, "food_id": food, "quantity": 1, "checked": k < int(ITEMS * CHECKED)}
                for k, food in enumerate(chosen)
            ]
            client.post("/api/households/shopping/items/create-bulk", json=items).raise_for_status()
        total = client.get("/api/households/shopping/items", params={"perPage": 1}).raise_for_status().json()
        food_total = client.get("/api/foods", params={"perPage": 1}).raise_for_status().json()
    print(json.dumps({"items": total.get("total"), "foods": food_total.get("total"), "asked": {
        "foods": FOODS, "lists": LISTS, "items": LISTS * ITEMS, "checked_share": CHECKED, "seed": SEED}}))  # fmt: skip


if __name__ == "__main__":
    main()
