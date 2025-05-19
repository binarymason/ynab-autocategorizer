import os
import json
import argparse
import requests
from datetime import datetime
import base64
from openai import OpenAI
from ynab import get_categories, get_all_transactions

from nacl import encoding, public  # Requires PyNaCl

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

def update_github_secret(repo, secret_name, secret_value, github_token):
    """Encrypt and upload secret to GitHub via REST API."""
    headers = {
        "Authorization": f"Bearer {github_token}",
        "Accept": "application/vnd.github+json"
    }

    # Step 1: Get public key
    key_url = f"https://api.github.com/repos/{repo}/actions/secrets/public-key"
    response = requests.get(key_url, headers=headers)
    response.raise_for_status()
    key_data = response.json()
    key_id = key_data["key"]
    key_id_str = key_data["key_id"]

    # Step 2: Encrypt the secret
    def encrypt(public_key_str, secret_value_str):
        public_key = public.PublicKey(public_key_str.encode("utf-8"), encoding.Base64Encoder())
        sealed_box = public.SealedBox(public_key)
        encrypted = sealed_box.encrypt(secret_value_str.encode("utf-8"))
        return base64.b64encode(encrypted).decode("utf-8")

    encrypted_value = encrypt(key_id, secret_value)

    # Step 3: Upload secret
    secret_url = f"https://api.github.com/repos/{repo}/actions/secrets/{secret_name}"
    payload = {
        "encrypted_value": encrypted_value,
        "key_id": key_id_str
    }
    put_resp = requests.put(secret_url, headers=headers, json=payload)
    put_resp.raise_for_status()
    print(f"🔐 GitHub secret '{secret_name}' updated successfully.")

def maybe_update_github_secret(entries):
    token = os.getenv("GITHUB_TOKEN")
    repo = os.getenv("GITHUB_REPO")
    if not (token and repo):
        print("ℹ️ GITHUB_TOKEN and GITHUB_REPO not set. Skipping secret upload.")
        return

    # Ask for confirmation
    try:
        confirm = input(f"\n❓ Do you want to update the 'YNAB_PAYEE_MAP' GitHub secret in '{repo}'? [y/N]: ").strip().lower()
        if confirm != "y":
            print("🚫 Skipping GitHub secret update.")
            return
    except EOFError:
        print("⚠️ No input detected. Skipping secret update.")
        return

    try:
        b64_payload = base64.b64encode(json.dumps(entries).encode("utf-8")).decode("utf-8")
        update_github_secret(
            repo=repo,
            secret_name="YNAB_PAYEE_MAP",
            secret_value=b64_payload,
            github_token=token
        )
    except Exception as e:
        print(f"⚠️ Failed to update GitHub secret: {e}")


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

    maybe_update_github_secret(entries)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Regenerate payee → category mapping from YNAB.")
    parser.add_argument("budget_id", help="The YNAB budget ID")
    parser.add_argument("--llm", action="store_true", help="Use LLM to optimize payee map")
    args = parser.parse_args()
    retrain_payee_map(args.budget_id, use_llm=args.llm)
