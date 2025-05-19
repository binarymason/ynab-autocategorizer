import os
import requests

YNAB_API_TOKEN = os.getenv("YNAB_API_TOKEN")

if not YNAB_API_TOKEN:
    raise EnvironmentError("Missing YNAB_API_TOKEN in environment variables.")

HEADERS = {
    "Authorization": f"Bearer {YNAB_API_TOKEN}",
    "Content-Type": "application/json"
}

def get_categories(budget_id):
    url = f"https://api.ynab.com/v1/budgets/{budget_id}/categories"
    response = requests.get(url, headers=HEADERS)
    response.raise_for_status()
    groups = response.json()["data"]["category_groups"]
    return [cat for group in groups for cat in group["categories"] if not cat["deleted"]]

def get_accounts(budget_id):
    url = f"https://api.ynab.com/v1/budgets/{budget_id}/accounts"
    response = requests.get(url, headers=HEADERS)
    response.raise_for_status()
    return response.json()["data"]["accounts"]

def get_all_transactions(budget_id):
    url = f"https://api.ynab.com/v1/budgets/{budget_id}/transactions"
    response = requests.get(url, headers=HEADERS)
    response.raise_for_status()
    return response.json()["data"]["transactions"]

def get_unapproved_transactions(budget_id):
    return [txn for txn in get_all_transactions(budget_id) if not txn["approved"]]

def update_transaction(budget_id, transaction_id, category_id=None, memo=None, dry_run=False):
    if dry_run:
        print(f"💡 DRY RUN: Would approve transaction {transaction_id} with "
              f"{'category ' + category_id if category_id else 'no category'}, flag as blue, memo='{memo}'")
        return None

    url = f"https://api.ynab.com/v1/budgets/{budget_id}/transactions/{transaction_id}"
    transaction_data = {
        "approved": True,
        "flag_color": "blue"
    }
    if category_id is not None:
        transaction_data["category_id"] = category_id
    if memo is not None:
        transaction_data["memo"] = memo

    data = {"transaction": transaction_data}
    response = requests.put(url, headers=HEADERS, json=data)
    response.raise_for_status()
    return response.json()
