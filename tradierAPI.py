# Nelson Dane
# Tradier API

import json
import os
import traceback
from time import sleep

import requests
from dotenv import load_dotenv

from helperAPI import Brokerage, maskString, printAndDiscord, printHoldings, stockOrder


def make_request(
    endpoint, BEARER_TOKEN, data=None, params=None, method="GET"
) -> dict | None:
    try:
        if method == "GET":
            response = requests.get(
                f"https://api.tradier.com/v1/{endpoint}",
                data=data,
                params=params,
                headers={
                    "Authorization": f"Bearer {BEARER_TOKEN}",
                    "Accept": "application/json",
                },
            )
        elif method == "POST":
            response = requests.post(
                f"https://api.tradier.com/v1/{endpoint}",
                data=data,
                params=params,
                headers={
                    "Authorization": f"Bearer {BEARER_TOKEN}",
                    "Accept": "application/json",
                },
            )
        else:
            raise Exception(f"Invalid method: {method}")
        if response.status_code != 200:
            raise Exception(f"Status code: {response.status_code}")
        json_response = response.json()
        if json_response.get("fault") and json_response["fault"].get("faultstring"):
            raise Exception(json_response["fault"]["faultstring"])
        sleep(0.1)
        return json_response
    except Exception as e:
        print(f"Error making request to Tradier API {endpoint}: {e}")
        print(f"Response: {response}")
        print(traceback.format_exc())
        sleep(1)
        return None


def tradier_init(API_METADATA=None):
    # Initialize .env file
    load_dotenv()
    EXTERNAL_CREDENTIALS = None
    CURRENT_USER_ID = None
    if API_METADATA:
        EXTERNAL_CREDENTIALS = API_METADATA.get("EXTERNAL_CREDENTIALS")
        CURRENT_USER_ID = API_METADATA.get("CURRENT_USER_ID")
    # Import Tradier account
    if not os.getenv("TRADIER") and EXTERNAL_CREDENTIALS is None:
        print("Tradier not found, skipping...")
        return None
    # Get access token and split into list
    accounts = (
        os.environ["TRADIER"].strip().split(",")
        if EXTERNAL_CREDENTIALS is None
        else EXTERNAL_CREDENTIALS.strip().split(",")
    )
    # Login to each account
    tradier_obj = Brokerage("Tradier")
    print("Logging in to Tradier...")
    for account in accounts:
        name = f"{CURRENT_USER_ID}-Tradier {accounts.index(account) + 1}"
        json_response = make_request("user/profile", account)
        if json_response is None:
            continue
        # Multiple accounts have different JSON structure
        if "'account': {'" in str(json_response):
            account_num = 1
        else:
            account_num = len(json_response["profile"]["account"])
        print(f"Tradier accounts found: {account_num}")
        for x in range(account_num):
            if account_num == 1:
                an = json_response["profile"]["account"]["account_number"]
                at = json_response["profile"]["account"]["type"]
            else:
                an = json_response["profile"]["account"][x]["account_number"]
                at = json_response["profile"]["account"][x]["type"]
            print(maskString(an))
            tradier_obj.set_account_number(name, an)
            tradier_obj.set_account_type(name, an, at)
            # Get balances
            json_balances = make_request(f"accounts/{an}/balances", account)
            if json_balances is None:
                tradier_obj.set_account_totals(name, an, 0)
                continue
            tradier_obj.set_account_totals(
                name, an, json_balances["balances"]["total_equity"]
            )
        # Get balances
        tradier_obj.set_logged_in_object(name, account)
    print("Logged in to Tradier!")
    return tradier_obj


async def tradier_holdings(
    tradier_o: Brokerage,
    loop=None,
    API_METADATA=None,
    botObj=None,
):
    CURRENT_USER_ID = API_METADATA.get("CURRENT_USER_ID")
    # Loop through accounts
    for key in tradier_o.get_account_numbers():
        for account_number in tradier_o.get_account_numbers(key):
            obj: str = tradier_o.get_logged_in_objects(key)
            try:
                # Get holdings from API
                json_response = make_request(
                    f"accounts/{account_number}/positions", obj
                )
                if json_response is None:
                    continue
                stocks = []
                amounts = []
                # Check if there are no holdings
                if json_response["positions"] == "null":
                    continue
                # Check if there's only one holding
                if "symbol" in json_response["positions"]["position"]:
                    stocks.append(json_response["positions"]["position"]["symbol"])
                    amounts.append(json_response["positions"]["position"]["quantity"])
                else:
                    # Loop through holdings
                    for stock in json_response["positions"]["position"]:
                        stocks.append(stock["symbol"])
                        amounts.append(stock["quantity"])
                # Get current price of each stock
                current_price = []
                for sym in stocks:
                    price_response = make_request(
                        "markets/quotes",
                        obj,
                        params={"symbols": sym, "greeks": "false"},
                    )
                    if (
                        price_response is None
                        or price_response["quotes"].get("quote") is None
                        or price_response["quotes"]["quote"].get("last") is None
                    ):
                        current_price.append(0)
                    else:
                        current_price.append(price_response["quotes"]["quote"]["last"])
                # Print and send them
                for position in stocks:
                    # Set index for easy use
                    i = stocks.index(position)
                    tradier_o.set_holdings(
                        key, account_number, position, amounts[i], current_price[i]
                    )
            except Exception as e:
                printAndDiscord(f"{key}: Error getting holdings: {e}", loop=loop)
                print(traceback.format_exc())
                continue
    # await printHoldings(tradier_o, loop=loop)
    await printHoldings(
        botObj,
        CURRENT_USER_ID,
        tradier_o,
        loop,
        False,
    )


def tradier_transaction(tradier_o: Brokerage, orderObj: stockOrder, loop=None):
    print()
    print("==============================")
    print("Tradier")
    print("==============================")
    print()
    # Loop through accounts
    for s in orderObj.get_stocks():
        for key in tradier_o.get_account_numbers():
            printAndDiscord(
                f"{key}: {orderObj.get_action()}ing {orderObj.get_amount()} of {s}",
                loop=loop,
            )
            for account in tradier_o.get_account_numbers(key):
                obj: str = tradier_o.get_logged_in_objects(key)
                print_account = maskString(account)
                # Tradier doesn't support fractional shares
                if not orderObj.get_amount().is_integer():
                    printAndDiscord(
                        f"Tradier account {print_account} Error: Fractional share {orderObj.get_amount()} not supported",
                        loop=loop,
                    )
                    continue
                if not orderObj.get_dry():
                    try:
                        data = {
                            "class": "equity",
                            "symbol": s,
                            "side": orderObj.get_action(),
                            "quantity": orderObj.get_amount(),
                            "type": "market",
                            "duration": "day",
                        }
                        json_response = make_request(
                            f"accounts/{account}/orders", obj, data=data, method="POST"
                        )
                        if json_response is None:
                            printAndDiscord(
                                f"Tradier account {print_account} Error: JSON response is None",
                                loop=loop,
                            )
                            continue
                        if json_response.get("order", {}).get("status") is not None:
                            printAndDiscord(
                                f"Tradier account {print_account}: {orderObj.get_action()} {orderObj.get_amount()} of {s}: {json_response['order']['status']}",
                                loop=loop,
                            )
                            continue
                        printAndDiscord(
                            f"Tradier account {print_account} Error: This order did not route. JSON response: {json.dumps(json_response, indent=2)}",
                            loop=loop,
                        )
                    except Exception as e:
                        if json_response:
                            errors = ". ".join(
                                json_response.get("errors", {}).get("error", [])
                            )
                            e = errors
                        printAndDiscord(
                            f"Tradier account {print_account} Error: {e}", loop=loop
                        )
                        print(traceback.format_exc())
                        print(f"JSON response: {json.dumps(json_response, indent=2)}")
                        continue
                else:
                    printAndDiscord(
                        f"Tradier account {print_account}: Running in DRY mode. Trasaction would've been: {orderObj.get_action()} {orderObj.get_amount()} of {s}",
                        loop=loop,
                    )
