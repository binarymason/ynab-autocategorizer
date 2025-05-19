import os
import json
import argparse
import requests
from datetime import datetime
from openai import OpenAI

from ynab import (
    get_categories,
    get_all_transactions
)

YNAB_API_TOKEN = os.getenv("YNAB_API_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
PAYEE_MAP_FILE = "payee_map.json"

if not YNAB_API_TOKEN or not OPENAI_API_KEY:
    raise EnvironmentError("Missing YNAB_API_TOKEN or OPENAI_API_KEY")

client = OpenAI(api_key=OPENAI_API_KEY)
OPENAI_MODEL = "gpt-4"


def generate_initial_map(transactions, category_by_id):
    mapping = {}
    for txn in transactions:
        if txn.get("flag_color") == "blue":
            continue
        if not txn["approved"] or not txn.get("payee_name") or not txn.get("category_id"):
            continue
        category_name = category_by_id.get(txn["category_id"])
        if category_name:
            mapping[txn["payee_name"]] = category_name
    return mapping

def build_map_entries(mapping):
    return [
        {
            "pattern": payee,
            "category": category,
            "regex": False,
            "locked": False
        }
        for payee, category in sorted(mapping.items())
    ]

def improve_map_with_llm(entries):
    import json as pyjson
    system_prompt = (
        "You are an expert budget assistant helping optimize a payee-to-category map.\n\n"
        "You will receive a list of entries like: { pattern, category, regex, locked }.\n"
        "- You MAY consolidate patterns using regex if helpful (e.g. 'Amazon.*').\n"
        "- You MUST NOT modify or remove entries where locked is true.\n"
        "- Return ONLY a revised JSON list in the same format."
    )

    user_prompt = f"Here is the current payee map:\n\n{pyjson.dumps(entries, indent=2)}"

    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0.3
    )

    revised_json = response.choices[0].message.content.strip()

    try:
        start = revised_json.index('[')
        end = revised_json.rindex(']') + 1
        return pyjson.loads(revised_json[start:end])
    except Exception:
        print("⚠️ Failed to parse LLM output correctly. Returning original entries.")
        return entries

def backup_if_changed(filepath, new_data):
    """Backup existing file only if its content differs from new_data."""
    if not os.path.exists(filepath):
        return

    with open(filepath, "r") as f:
        try:
            existing_data = json.load(f)
        except json.JSONDecodeError:
            existing_data = None

    if existing_data == new_data:
        print("ℹ️ No changes to payee map. Skipping backup.")
        return

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = f"{os.path.splitext(filepath)[0]}.backup-{timestamp}.json"
    os.rename(filepath, backup_path)
    print(f"📦 Backup of existing payee map saved to: {backup_path}")

def retrain_payee_map(budget_id, use_llm=False):
    print("Retraining payee map from approved, non-blue transactions...")
    categories = get_categories(budget_id)
    category_by_id = {c["id"]: c["name"] for c in categories}
    transactions = get_all_transactions(budget_id)

    initial_mapping = generate_initial_map(transactions, category_by_id)
    entries = build_map_entries(initial_mapping)

    if use_llm:
        print("🔍 Improving map with LLM assistance...")
        entries = improve_map_with_llm(entries)

    backup_if_changed(PAYEE_MAP_FILE, entries)

    with open(PAYEE_MAP_FILE, "w") as f:
        json.dump(entries, f, indent=2)

    print(f"✅ Payee map saved with {len(entries)} entries.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Regenerate payee → category mapping from YNAB.")
    parser.add_argument("budget_id", help="The YNAB budget ID")
    parser.add_argument("--llm", action="store_true", help="Use LLM to optimize payee map")
    args = parser.parse_args()
    retrain_payee_map(args.budget_id, use_llm=args.llm)
