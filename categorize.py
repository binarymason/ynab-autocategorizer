import os
import json
import re
import argparse
import requests
from openai import OpenAI
from ynab import (
    get_categories,
    get_accounts,
    get_unapproved_transactions,
    update_transaction
)

# ========== CONFIGURATION ==========
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
YNAB_API_TOKEN = os.getenv("YNAB_API_TOKEN")
PAYEE_MAP_FILE = "payee_map.json"

if not OPENAI_API_KEY or not YNAB_API_TOKEN:
    raise EnvironmentError("Missing OPENAI_API_KEY or YNAB_API_TOKEN in environment variables.")

client = OpenAI(api_key=OPENAI_API_KEY)
OPENAI_MODEL = "gpt-4"


# ========== OPENAI CATEGORIZATION ==========

def choose_category_llm(transaction, category_names, account_names):
    import json as pyjson
    prompt = f"""You are a budgeting assistant. Your job is to assign a category to a financial transaction based on its payee, memo, and amount.

Only respond in the following JSON format:
{{"category": "<category_name>", "confidence": <float from 0.0 to 1.0>}}

Valid categories:
{', '.join(category_names)}

The user has the following accounts:
{', '.join(account_names)}

Transaction details:
Payee: {transaction.get("payee_name", "")}
Memo: {transaction.get("memo", "")}
Amount: {transaction["amount"] / 1000:.2f}
Account used: {transaction.get("account_name", "Unknown")}
"""

    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": "You only respond in valid JSON. Do not explain anything."},
            {"role": "user", "content": prompt}
        ],
        temperature=0
    )

    content = response.choices[0].message.content.strip()
    result = pyjson.loads(content)
    return result["category"].strip(), result.get("confidence", 0)

# ========== PAYEE MAP HANDLING ==========

def load_payee_map():
    if os.path.exists(PAYEE_MAP_FILE):
        with open(PAYEE_MAP_FILE, "r") as f:
            return json.load(f)
    return []

def find_mapped_category(payee, payee_map):
    for entry in payee_map:
        pattern = entry.get("pattern")
        if entry.get("regex", False):
            if re.search(pattern, payee):
                return entry["category"]
        else:
            if pattern == payee:
                return entry["category"]
    return None

# ========== MAIN SCRIPT ==========

def main():
    parser = argparse.ArgumentParser(description="Categorize and approve YNAB transactions using OpenAI.")
    parser.add_argument("budget_id", help="The YNAB budget ID")
    parser.add_argument("--dry-run", action="store_true", help="Simulate actions without making changes")
    args = parser.parse_args()

    print("Fetching categories and accounts...")
    categories = get_categories(args.budget_id)
    accounts = get_accounts(args.budget_id)
    category_names = [cat["name"] for cat in categories]
    account_names = [acct["name"] for acct in accounts]
    category_by_name = {c["name"]: c["id"] for c in categories}
    payee_map = load_payee_map()

    print("Fetching unapproved transactions...")
    unapproved = get_unapproved_transactions(args.budget_id)
    print(f"Found {len(unapproved)} unapproved transactions.")

    for txn in unapproved:
        try:
            if txn.get("transfer_account_id"):
                print(f"🔁 Approving transfer transaction {txn['id']} ({txn.get('payee_name', '')})")
                update_transaction(args.budget_id, txn["id"], None, dry_run=args.dry_run)
                print(f"✅ Transfer approved{' (dry run)' if args.dry_run else ''}.")
                continue

            payee = txn.get("payee_name", "")
            print(f"\nProcessing transaction {txn['id']}: {payee} - {txn.get('memo', '')}")

            category_name = find_mapped_category(payee, payee_map)
            confidence_pct = None

            if category_name:
                print(f"📌 Using mapped category for payee '{payee}': {category_name}")
            else:
                category_name, confidence = choose_category_llm(txn, category_names, account_names)
                confidence_pct = int(confidence * 100)
                print(f"🤖 LLM chose: {category_name} ({confidence_pct}%)")

            # Update memo with LLM confidence if applicable
            base_memo = txn.get("memo", "") or ""
            if confidence_pct is not None:
                memo = f"{base_memo} | 🤖 {confidence_pct}% confident".strip()
            else:
                memo = base_memo

            matched_category_id = category_by_name.get(category_name)
            if matched_category_id:
                update_transaction(args.budget_id, txn["id"], matched_category_id, dry_run=args.dry_run, memo=memo)
                print(f"✅ Categorized as '{category_name}' and approved{' (dry run)' if args.dry_run else ''}.")
            else:
                print(f"⚠️ Category '{category_name}' not found. Skipping.")
        except Exception as e:
            print(f"❌ Failed to process transaction {txn['id']}: {e}")

    print("\nAll done!")

if __name__ == "__main__":
    main()
