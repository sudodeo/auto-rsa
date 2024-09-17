# Nelson Dane
# Schwab API

import asyncio
import os
import traceback
from time import sleep

from dotenv import load_dotenv
from schwab_api import Schwab

from helperAPI import Brokerage, maskString, printAndDiscord, printHoldings, stockOrder


async def schwab_init(API_METADATA=None):
    # Initialize .env file
    load_dotenv()
    EXTERNAL_CREDENTIALS = None
    CURRENT_USER_ID = None
    if API_METADATA:
        EXTERNAL_CREDENTIALS = API_METADATA.get("EXTERNAL_CREDENTIALS")
        CURRENT_USER_ID = API_METADATA.get("CURRENT_USER_ID")
    
    # Import Schwab account
    if not os.getenv("SCHWAB") and EXTERNAL_CREDENTIALS is None:
        print("Schwab not found, skipping...")
        return None
    
    accounts = (
        os.environ["SCHWAB"].strip().split(",")
        if EXTERNAL_CREDENTIALS is None
        else EXTERNAL_CREDENTIALS.strip().split(",")
    )
    
    # Log in to Schwab account
    print("Logging in to Schwab...")
    schwab_obj = Brokerage("Schwab")
    
    for account in accounts:
        index = accounts.index(account) + 1
        name = f"{CURRENT_USER_ID}-Schwab {index}"
        try:
            account = account.split(":")
            schwab = Schwab(
                session_cache=f"./creds/schwab_{CURRENT_USER_ID}_{index}.json"
            )

            # Move the login process to a separate thread
            logged_in = await asyncio.to_thread(
                schwab.login,
                username=account[0],
                password=account[1],
                totp_secret=None if account[2].upper() == "NA" else account[2],
            )
            
            if not logged_in:
                raise Exception("Login failed")
            
            print("getting account info...")
            account_info = schwab.get_account_info_v2()
            account_list = list(account_info.keys())
            print_accounts = [maskString(a) for a in account_list]
            print(f"The following Schwab accounts were found: {print_accounts}")
            print("Logged in to Schwab!")
            schwab_obj.set_logged_in_object(name, schwab)
            
            for account in account_list:
                schwab_obj.set_account_number(name, account)
                schwab_obj.set_account_totals(
                    name, account, account_info[account]["account_value"]
                )
        
        except Exception as e:
            print(f"Error logging in to Schwab: {e}")
            print(traceback.format_exc())
            return None
    
    return schwab_obj


async def schwab_holdings(
    schwab_o: Brokerage,
    loop=None,
    API_METADATA=None,
    botObj=None,
):
    CURRENT_USER_ID = API_METADATA.get("CURRENT_USER_ID")
    # Get holdings on each account
    for key in schwab_o.get_account_numbers():
        obj: Schwab = schwab_o.get_logged_in_objects(key)
        all_holdings = obj.get_account_info_v2()
        for account in schwab_o.get_account_numbers(key):
            try:
                holdings = all_holdings[account]["positions"]
                for item in holdings:
                    sym = item["symbol"]
                    if sym == "":
                        sym = "Unknown"
                    mv = round(float(item["market_value"]), 2)
                    qty = float(item["quantity"])
                    # Schwab doesn't return current price, so we have to calculate it
                    if qty == 0:
                        current_price = 0
                    else:
                        current_price = round(mv / qty, 2)
                    schwab_o.set_holdings(key, account, sym, qty, current_price)
            except Exception as e:
                printAndDiscord(f"{key} {account}: Error getting holdings: {e}", loop)
                print(traceback.format_exc())
    # await printHoldings(schwab_o, loop)
    await printHoldings(
        botObj,
        CURRENT_USER_ID,
        schwab_o,
        loop,
        False,
    )


def schwab_transaction(schwab_o: Brokerage, orderObj: stockOrder, loop=None):
    print()
    print("==============================")
    print("Schwab")
    print("==============================")
    print()
    # Buy on each account
    for s in orderObj.get_stocks():
        for key in schwab_o.get_account_numbers():
            printAndDiscord(
                f"{key} {orderObj.get_action()}ing {orderObj.get_amount()} {s} @ {orderObj.get_price()}",
                loop,
            )
            obj: Schwab = schwab_o.get_logged_in_objects(key)
            for account in schwab_o.get_account_numbers(key):
                print_account = maskString(account)
                # If DRY is True, don't actually make the transaction
                if orderObj.get_dry():
                    printAndDiscord(
                        "Running in DRY mode. No transactions will be made.", loop
                    )
                try:
                    messages, success = obj.trade_v2(
                        ticker=s,
                        side=orderObj.get_action().capitalize(),
                        qty=orderObj.get_amount(),
                        account_id=account,
                        dry_run=orderObj.get_dry(),
                    )
                    printAndDiscord(
                        (
                            f"{key} account {print_account}: The order verification was "
                            + "successful"
                            if success
                            else "unsuccessful, retrying..."
                        ),
                        loop,
                    )
                    if not success:
                        messages, success = obj.trade(
                            ticker=s,
                            side=orderObj.get_action().capitalize(),
                            qty=orderObj.get_amount(),
                            account_id=account,
                            dry_run=orderObj.get_dry(),
                        )
                        printAndDiscord(
                            (
                                f"{key} account {print_account}: The order verification was "
                                + "retry successful"
                                if success
                                else "retry unsuccessful"
                            ),
                            loop,
                        )
                        printAndDiscord(
                            f"{key} account {print_account}: The order verification produced the following messages: {messages}",
                            loop,
                        )
                except Exception as e:
                    printAndDiscord(
                        f"{key} {print_account}: Error submitting order: {e}", loop
                    )
                    print(traceback.format_exc())
                sleep(1)
