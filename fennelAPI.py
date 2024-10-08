import asyncio
import os
import traceback

from dotenv import load_dotenv
from fennel_invest_api import Fennel

from helperAPI import (
    Brokerage,
    getOTPCodeDiscord,
    printAndDiscord,
    printHoldings,
    stockOrder,
)


async def fennel_init(API_METADATA=None, botObj=None, loop=None):
    # Initialize .env file
    load_dotenv()
    EXTERNAL_CREDENTIALS = None
    CURRENT_USER_ID = None
    if API_METADATA:
        EXTERNAL_CREDENTIALS = API_METADATA.get("EXTERNAL_CREDENTIALS")
        CURRENT_USER_ID = API_METADATA.get("CURRENT_USER_ID")
    # Import Fennel account
    fennel_obj = Brokerage("Fennel")
    if not os.getenv("FENNEL") and EXTERNAL_CREDENTIALS is None:
        print("Fennel not found, skipping...")
        return None
    FENNEL = (
        os.environ["FENNEL"].strip().split(",")
        if EXTERNAL_CREDENTIALS is None
        else EXTERNAL_CREDENTIALS.strip().split(",")
    )
    # Log in to Fennel account
    print(f"Logging in to Fennel for user {CURRENT_USER_ID}...")
    for index, account in enumerate(FENNEL):
        name = f"{CURRENT_USER_ID}-Fennel {index + 1}"
        try:
            fb = Fennel(
                filename=f"fennel_{CURRENT_USER_ID}_{index + 1}.pkl",
                path=f"./creds/{CURRENT_USER_ID}/",
            )
            try:
                if botObj is None and loop is None:
                    # Login from CLI
                    fb.login(
                        email=account,
                        wait_for_code=True,
                    )
                else:
                    # Login from Discord and check for 2fa required message
                    fb.login(
                        email=account,
                        wait_for_code=False,
                    )
            except Exception as e:
                if "2FA" in str(e) and botObj is not None and loop is not None:
                    # Sometimes codes take a long time to arrive
                    timeout = 300  # 5 minutes
                    try:
                        otp_code = await getOTPCodeDiscord(
                            botObj, CURRENT_USER_ID, name, timeout=timeout, loop=loop
                        )
                        if otp_code is None:
                            raise Exception("No 2FA code found")
                        fb.login(
                            email=account,
                            wait_for_code=False,
                            code=otp_code,
                        )
                    except Exception as e:
                        print(f"Error logging in to Fennel(2FA): {e}")
                        print(traceback.format_exc())
                        continue
                else:
                    raise e
            fennel_obj.set_logged_in_object(name, fb, "fb")
            full_accounts = fb.get_full_accounts()
            for a in full_accounts:
                b = fb.get_portfolio_summary(a["id"])
                fennel_obj.set_account_number(name, a["name"])
                fennel_obj.set_account_totals(
                    name,
                    a["name"],
                    b["cash"]["balance"]["canTrade"],
                )
                fennel_obj.set_logged_in_object(name, a["id"], a["name"])
                print(f"Found account {a['name']}")
            print(f"{name}: Logged in")
        except Exception as e:
            print(f"Error logging into Fennel: {e}")
            print(traceback.format_exc())
            continue
    print("Logged into Fennel!")
    return fennel_obj


async def fennel_holdings(
    fbo: Brokerage,
    loop=None,
    API_METADATA=None,
    botObj=None,
):
    CURRENT_USER_ID = API_METADATA.get("CURRENT_USER_ID")
    for key in fbo.get_account_numbers():
        for account in fbo.get_account_numbers(key):
            obj: Fennel = fbo.get_logged_in_objects(key, "fb")
            account_id = fbo.get_logged_in_objects(key, account)
            try:
                # Get account holdings
                positions = obj.get_stock_holdings(account_id)
                if positions != []:
                    for holding in positions:
                        qty = holding["investment"]["ownedShares"]
                        if float(qty) == 0:
                            continue
                        sym = holding["security"]["ticker"]
                        cp = holding["security"]["currentStockPrice"]
                        if cp is None:
                            cp = "N/A"
                        fbo.set_holdings(key, account, sym, qty, cp)
            except Exception as e:
                printAndDiscord(f"Error getting Fennel holdings: {e}")
                print(traceback.format_exc())
                continue
    await printHoldings(
        botObj,
        CURRENT_USER_ID,
        fbo,
        loop,
        False,
    )


def fennel_transaction(fbo: Brokerage, orderObj: stockOrder, loop=None):
    print()
    print("==============================")
    print("Fennel")
    print("==============================")
    print()
    for s in orderObj.get_stocks():
        for key in fbo.get_account_numbers():
            printAndDiscord(
                f"{key}: {orderObj.get_action()}ing {orderObj.get_amount()} of {s}",
                loop,
            )
            for account in fbo.get_account_numbers(key):
                obj: Fennel = fbo.get_logged_in_objects(key, "fb")
                account_id = fbo.get_logged_in_objects(key, account)
                try:
                    order = obj.place_order(
                        account_id=account_id,
                        ticker=s,
                        quantity=orderObj.get_amount(),
                        side=orderObj.get_action(),
                        dry_run=orderObj.get_dry(),
                    )
                    if orderObj.get_dry():
                        message = "Dry Run Success"
                        if not order.get("dry_run_success", False):
                            message = "Dry Run Failed"
                    else:
                        message = "Success"
                        if order.get("data", {}).get("createOrder") != "pending":
                            message = order.get("data", {}).get("createOrder")
                    printAndDiscord(
                        f"{key}: {orderObj.get_action()} {orderObj.get_amount()} of {s} in {account}: {message}",
                        loop,
                    )
                except Exception as e:
                    printAndDiscord(f"{key} {account}: Error placing order: {e}", loop)
                    print(traceback.format_exc())
                    continue
