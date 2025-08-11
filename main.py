import json
import os
from dataclasses import dataclass
from datetime import date

import flask
import functions_framework
import ynab
from dotenv import load_dotenv
from flask import make_response
from google.cloud import secretmanager


@dataclass
class TransactionPostDto:
    """
    Represents data submitted as a POST request to the cloud function
    Sample POST request:
    {
        "amount": "$6.22",
        "name": "Grocery Store Name",
        "card": "Bank Name",
        "merchant": "Grocery Store Name",
        "date": "2025-08-09T21:26:45-04:00"
    }
    """

    amount: str
    name: str
    card: str
    merchant: str
    date: str


def get_secret(secret_id: str, project_id: str, version: str = "latest") -> str:
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{project_id}/secrets/{secret_id}/versions/{version}"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("UTF-8")


load_dotenv()

project_id = os.environ.get("GCP_PROJECT_ID", "")
ynab_secrets_raw = os.environ.get("YNAB_SECRETS", get_secret("ynab", project_id))
ynab_secrets = json.loads(ynab_secrets_raw)

BUDGET_ID = ynab_secrets.get("budget_id", "")
ynab_config = ynab.Configuration(access_token=ynab_secrets.get("access_token", ""))
api_client = ynab.ApiClient(ynab_config)


def parse_amount(amount_str: str) -> int:
    """
    Return the amount in YNAB's milliunit format
    https://api.youneedabudget.com/#formats
    """
    amount_str = amount_str.replace("$", "").strip()
    try:
        return int(float(amount_str) * 1000)
    except ValueError:
        print(f"Failed to parse amount: {amount_str}")
        raise TypeError(f"Invalid amount format: {amount_str}")


def parse_date(date_str: str) -> date:
    """
    Return the date in YYYY-MM-DD format
    """
    try:
        return date.fromisoformat(date_str.split("T")[0])
    except ValueError:
        print(f"Failed to parse date: {date_str}")
        raise TypeError(f"Invalid date format: {date_str}")


def get_account_id_from_card_name(card_name: str) -> str:
    """
    Return the account ID associated with the given card name
    """
    for account in ynab_secrets.get("accounts", []):
        if account.get("name") == card_name:
            return account.get("id")

    raise ValueError(f"Account ID not found for card: {card_name}")


def get_category_id_from_merchant_name(merchant_name: str) -> str | None:
    """
    Return the category ID associated with the given merchant name or None if not found
    """
    for merchant in ynab_secrets.get("merchants", []):
        if merchant.get("name") == merchant_name:
            return merchant.get("category_id")

    return None


def parse_transaction(transactionDto: TransactionPostDto) -> ynab.NewTransaction:
    transaction = ynab.NewTransaction(
        account_id=get_account_id_from_card_name(transactionDto.card),
        date=parse_date(transactionDto.date),
        amount=parse_amount(transactionDto.amount),
        payee_name=transactionDto.merchant,
        category_id=get_category_id_from_merchant_name(transactionDto.merchant),
    )

    return transaction


def post_transaction(api_client: ynab.ApiClient, transaction: ynab.NewTransaction):
    """
    Post the transaction to the YNAB API
    """
    with api_client:
        api_instance = ynab.TransactionsApi(api_client)
        data = ynab.PostTransactionsWrapper(transaction=transaction)
        api_instance.create_transaction(BUDGET_ID, data)


@functions_framework.http
def process_request(request: flask.Request) -> flask.Response:
    """HTTP Cloud Function.
    Args:
        request (flask.Request): The request object.
        <https://flask.palletsprojects.com/en/1.1.x/api/#incoming-request-data>
    Returns:
        The response text, or any set of values that can be turned into a
        Response object using `make_response`
        <https://flask.palletsprojects.com/en/1.1.x/api/#flask.make_response>.
    Note:
        For more information on how Flask integrates with Cloud
        Functions, see the `Writing HTTP functions` page.
        <https://cloud.google.com/functions/docs/writing/http#http_frameworks>
    """
    if request.method != "POST":
        return make_response("Method Not Allowed", 405)

    data = request.get_json()

    try:
        transactionDto = TransactionPostDto(**data)
    except Exception:
        print(f"Failed to parse request data: {data}")
        return make_response("Bad Request: Invalid request format.", 400)

    try:
        transaction = parse_transaction(transactionDto)
    except Exception as e:
        print(f"Failed to parse transaction: {transactionDto}")
        return make_response(f"Bad Request: {e}", 400)

    try:
        post_transaction(api_client=api_client, transaction=transaction)
    except Exception as e:
        print(f"YNAB API Error: {e}")
        return make_response("Unable to Post Transaction", 500)

    if not transaction.category_id:
        msg = f"{transactionDto.merchant} needs to be categorized"
        print(msg)
        resp = make_response(f"Transaction Posted. {msg}", 200)
    else:
        resp = make_response("Transaction Posted", 200)

    return resp
