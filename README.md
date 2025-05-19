# YNAB Auto Categorizer

This is a simple tool that uses AI to categorize your YNAB transactions.

You need two environment variables in your system to make this work:

- `YNAB_API_TOKEN` You can generate a token here: https://app.ynab.com/settings/developer
- `OPENAI_API_KEY` Generate a token from here: https://platform.openai.com/

## Creating a payee list.

To save on costs, you can create a list of payees. The categorizer will try to use this first before asking an LLM.

To update your payee map, do the following command:

```sh

python retrain.py <ynab-budget-id>
```

To update your payee map and optionally have an LLM improve it automatically do this:

```sh

python retrain.py <ynab-budget-id> --llm

```

If you want to instruct the LLM to never update a payee pattern, edit the payee map JSON file and set `locked: true`.


## Automatically categorizing transactions

To automatically categorize transactions but perform a dry run before updating YNAB, run the following command:

```sh
python categorize.py <ynab-budget-id>  --dry-run

```

To update YNAB with the AI's categorizations, run without the `--dry-run` flag:

```sh
python categorize.py <ynab-budget-id>
```
