# Nelson Dane
# Script to automate RSA stock purchases

# Import libraries
import asyncio
import os
import sys
import aiosqlite
import traceback

import discord.ext.commands
import discord.ext
from cryptography.fernet import Fernet

from database_queries import FIND_ONE_BROKER_CREDENTIALS_FOR_USER

# Check Python version (minimum 3.10)
print("Python version:", sys.version)
if sys.version_info < (3, 10):
    print("ERROR: Python 3.10 or newer is required")
    sys.exit(1)
print()

try:
    import discord

    # from slash_commands import SlashCommands
    # from discord import app_commands
    from discord.ext import commands
    from dotenv import load_dotenv

    # Custom API libraries
    from chaseAPI import *
    from fennelAPI import *
    from fidelityAPI import *
    from firstradeAPI import *
    from helperAPI import (
        ThreadHandler,
        check_package_versions,
        printAndDiscord,
        stockOrder,
        updater,
    )
    from publicAPI import *
    from robinhoodAPI import *
    from schwabAPI import *
    from tastyAPI import *
    from tradierAPI import *
    from vanguardAPI import *
    from webullAPI import *
except Exception as e:
    print(f"Error importing libraries: {e}")
    print(traceback.format_exc())
    print("Please run 'pip install -r requirements.txt'")
    sys.exit(1)

# Initialize .env file
load_dotenv()

# Generate and store the encryption key (only once, or securely store it in your .env)
if not os.getenv("ENCRYPTION_KEY"):
    key = Fernet.generate_key()
    with open(".env", "a") as f:
        f.write(f"\nENCRYPTION_KEY={key.decode()}")
    print("Encryption key generated and stored in .env file.")
else:
    key = os.getenv("ENCRYPTION_KEY").encode()

cipher_suite = Fernet(key)

# Global variables
SUPPORTED_BROKERS = [
    "chase",
    "fennel",
    "fidelity",
    "firstrade",
    "public",
    "robinhood",
    "schwab",
    "tastytrade",
    "tradier",
    "vanguard",
    "webull",
]
DAY1_BROKERS = [
    "chase",
    "fennel",
    "firstrade",
    "public",
    "schwab",
    "tastytrade",
    "tradier",
    "webull",
]
DISCORD_BOT = False
DOCKER_MODE = False
DANGER_MODE = False
DATABASE_NAME = "rsa_bot_users.db"


# Account nicknames
def nicknames(broker):
    if broker in ["fid", "fido"]:
        return "fidelity"
    if broker == "ft":
        return "firstrade"
    if broker == "rh":
        return "robinhood"
    if broker == "tasty":
        return "tastytrade"
    if broker == "vg":
        return "vanguard"
    if broker == "wb":
        return "webull"
    return broker


# Encrypt credentials before storing them
def encrypt_credential(credential: str) -> str:
    return cipher_suite.encrypt(credential.encode()).decode()


# Decrypt credentials when retrieving them
def decrypt_credential(encrypted_credential: str) -> str:
    return cipher_suite.decrypt(encrypted_credential.encode()).decode()


# Runs the specified function for each broker in the list
# broker name + type of function
async def fun_run(author_id, orderObj: stockOrder, command, botObj=None, loop=None):
    if command in [("_init", "_holdings"), ("_init", "_transaction")]:
        try:
            if not botObj or not hasattr(botObj, "db") or botObj.db is None:
                botObj.db = await aiosqlite.connect(DATABASE_NAME)
            
            db = botObj.db

            # Check if the connection is active
            async with db.execute("SELECT 1") as cursor:
                await cursor.fetchone()

        except (ValueError, aiosqlite.Error) as e:
            print(f"Database connection error: {e}")
            # Optionally, try to reconnect here
            botObj.db = await aiosqlite.connect(DATABASE_NAME)
            db = botObj.db

        order_brokers = orderObj.get_brokers()
        if len(order_brokers) == 0:
            printAndDiscord(f"<@{author_id}> No brokers to run", loop)
            return
        for broker in order_brokers:
            # robin hood is currently unavailable
            if broker == "robinhood":
                # printAndDiscord(f"Robinhood is currently unavailable", loop)
                continue
            if broker in orderObj.get_notbrokers():
                continue

            async with db.execute(
                FIND_ONE_BROKER_CREDENTIALS_FOR_USER, (str(author_id), broker)
            ) as cursor:
                encrypted_credentials = await cursor.fetchone()
            if not encrypted_credentials:
                continue

            decrypted_credentials = decrypt_credential(encrypted_credentials[0])
            API_METADATA = {
                "EXTERNAL_CREDENTIALS": decrypted_credentials,
                "CURRENT_USER_ID": author_id,
            }

            broker = nicknames(broker)
            init_command, second_command = command
            try:
                # Initialize broker
                fun_name = broker + init_command
                if broker.lower() in ["fennel", "firstrade", "public"]:
                    # Requires bot object and loop
                    result = await globals()[fun_name](
                        API_METADATA=API_METADATA,
                        botObj=botObj,
                        loop=loop,
                    )
                    orderObj.set_logged_in(result, broker)
                elif broker.lower() in ["chase", "fidelity", "vanguard"]:
                    fun_name = broker + "_run"

                    # Playwright brokers have to run all transactions with one function
                    coroutine = globals()[fun_name](
                        orderObj=orderObj,
                        command=command,
                        botObj=botObj,
                        loop=loop,
                        API_METADATA=API_METADATA,
                    )

                    # Run the coroutine in the main event loop
                    future = asyncio.run_coroutine_threadsafe(coroutine, loop)
                    try:
                        result = (
                            future.result()
                        )  # This will block until the coroutine completes
                        if result is None:
                            raise RuntimeError(
                                f"Error in {fun_name}: Function did not complete successfully."
                            )
                    except Exception as err:
                        raise RuntimeError(f"Error in {fun_name}: {err}")
                elif broker.lower() == "schwab":
                    orderObj.set_logged_in(
                        await globals()[fun_name](API_METADATA=API_METADATA), broker
                    )
                else:
                    orderObj.set_logged_in(
                        globals()[fun_name](API_METADATA=API_METADATA), broker
                    )

                print()
                if broker.lower() not in ["chase", "vanguard"]:
                    # Verify broker is logged in
                    orderObj.order_validate(preLogin=False)
                    logged_in_broker = orderObj.get_logged_in(broker)
                    if logged_in_broker is None:
                        print(f"Error: {broker} not logged in, skipping...")
                        continue
                    # Get holdings or complete transaction
                    if second_command == "_holdings":
                        fun_name = broker + second_command
                        await globals()[fun_name](
                            logged_in_broker,
                            loop,
                            API_METADATA=API_METADATA,
                            botObj=botObj,
                        )
                    elif second_command == "_transaction":
                        fun_name = broker + second_command
                        globals()[fun_name](
                            logged_in_broker,
                            orderObj,
                            loop,
                        )
                        printAndDiscord(
                            f"All {broker.capitalize()} transactions complete",
                            loop,
                        )
            except Exception as ex:
                print(traceback.format_exc())
                print(f"Error in {fun_name} with {broker}: {ex}")
                print(orderObj)
            print()
        printAndDiscord("All commands complete in all registered brokers", loop)
    else:
        print(f"Error: {command} is not a valid command")


# Parse input arguments and update the order object
def argParser(args: list) -> stockOrder:
    args = [x.lower() for x in args]
    # Initialize order object
    orderObj = stockOrder()
    # If first argument is holdings, set holdings to true

    if args[0] == "holdings":
        orderObj.set_holdings(True)
        # Next argument is brokers
        if args[1] == "all":
            orderObj.set_brokers(SUPPORTED_BROKERS)
        elif args[1] == "day1":
            orderObj.set_brokers(DAY1_BROKERS)
        elif args[1] == "most":
            orderObj.set_brokers(
                list(filter(lambda x: x != "vanguard", SUPPORTED_BROKERS))
            )
        elif args[1] == "fast":
            orderObj.set_brokers(DAY1_BROKERS + ["robinhood"])
        else:
            for broker in args[1].split(","):
                orderObj.set_brokers(nicknames(broker))
        # If next argument is not, set not broker
        if len(args) > 3 and args[2] == "not":
            for broker in args[3].split(","):
                if nicknames(broker) in SUPPORTED_BROKERS:
                    orderObj.set_notbrokers(nicknames(broker))
        return orderObj
    # Otherwise: action, amount, stock, broker, (optional) not broker, (optional) dry
    if args[0] not in ["buy", "sell"]:
        raise Exception(f"Unsupported action: {args[0]}")
    orderObj.set_action(args[0])
    orderObj.set_amount(args[1])
    for stock in args[2].split(","):
        orderObj.set_stock(stock)
    # Next argument is a broker, set broker
    if args[3] == "all":
        orderObj.set_brokers(SUPPORTED_BROKERS)
    elif args[3] == "day1":
        orderObj.set_brokers(DAY1_BROKERS)
    elif args[3] == "most":
        orderObj.set_brokers(list(filter(lambda x: x != "vanguard", SUPPORTED_BROKERS)))
    elif args[3] == "fast":
        orderObj.set_brokers(DAY1_BROKERS + ["robinhood"])
    else:
        for broker in args[3].split(","):
            if nicknames(broker) in SUPPORTED_BROKERS:
                orderObj.set_brokers(nicknames(broker))
    # If next argument is not, set not broker
    if len(args) > 4 and args[4] == "not":
        for broker in args[5].split(","):
            if nicknames(broker) in SUPPORTED_BROKERS:
                orderObj.set_notbrokers(nicknames(broker))
    # If next argument is false, set dry to false
    if args[-1] == "false":
        orderObj.set_dry(False)
    # Validate order object
    orderObj.order_validate(preLogin=True)
    return orderObj


async def main():
    global DANGER_MODE, DOCKER_MODE, DISCORD_BOT

    # Determine if ran from command line
    if len(sys.argv) == 1:  # If no arguments, do nothing
        print("No arguments given, see README for usage")
        return

    # Check if danger mode is enabled
    if os.getenv("DANGER_MODE", "").lower() == "true":
        DANGER_MODE = True
        print("DANGER MODE ENABLED")
        print()

    # If docker argument, run docker bot
    if sys.argv[1].lower() == "docker":
        print("Running bot from docker")
        DOCKER_MODE = DISCORD_BOT = True
    # If discord argument, run discord bot, no docker, no prompt
    elif sys.argv[1].lower() == "discord":
        updater()
        check_package_versions()
        print("Running Discord bot from command line")
        DISCORD_BOT = True
    else:  # If any other argument, run bot, no docker or discord bot
        updater()
        check_package_versions()
        print("Running bot from command line")
        print()
        cliOrderObj = argParser(sys.argv[1:])
        if not cliOrderObj.get_holdings():
            print(f"Action: {cliOrderObj.get_action()}")
            print(f"Amount: {cliOrderObj.get_amount()}")
            print(f"Stock: {cliOrderObj.get_stocks()}")
            print(f"Time: {cliOrderObj.get_time()}")
            print(f"Price: {cliOrderObj.get_price()}")
            print(f"Broker: {cliOrderObj.get_brokers()}")
            print(f"Not Broker: {cliOrderObj.get_notbrokers()}")
            print(f"DRY: {cliOrderObj.get_dry()}")
            print()
            print("If correct, press enter to continue...")
            try:
                if not DANGER_MODE:
                    input("Otherwise, press ctrl+c to exit")
                    print()
            except KeyboardInterrupt:
                print()
                print("Exiting, no orders placed")
                return

        # Validate order object
        cliOrderObj.order_validate(preLogin=True)

        # Get holdings or complete transaction
        if cliOrderObj.get_holdings():
            await fun_run(cliOrderObj, ("_init", "_holdings"))
        else:
            await fun_run(cliOrderObj, ("_init", "_transaction"))

    # If discord bot, run discord bot
    if DISCORD_BOT:
        # Get discord token and channel from .env file
        if not os.environ["DISCORD_TOKEN"]:
            raise Exception("DISCORD_TOKEN not found in .env file, please add it")
        if not os.environ["DISCORD_CHANNEL"]:
            raise Exception("DISCORD_CHANNEL not found in .env file, please add it")
        if not os.environ["RSA_BOT_ROLE_ID"]:
            raise Exception("RSA_BOT_ROLE_ID not found in .env file, please add it")
        if not os.environ["RSA_ADMIN_ROLE_ID"]:
            raise Exception("RSA_ADMIN_ROLE_ID not found in .env file, please add it")
        DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
        DISCORD_CHANNEL = int(os.getenv("DISCORD_CHANNEL"))
        RSA_BOT_ROLE_ID = int(os.getenv("RSA_BOT_ROLE_ID"))
        RSA_MENTEE_ROLE_ID = int(os.getenv("RSA_MENTEE_ROLE_ID"))
        RSAUTOMATION_ROLE_ID = int(os.getenv("RSAUTOMATION_ROLE_ID"))

        RSA_ADMIN_ROLE_ID = int(os.getenv("RSA_ADMIN_ROLE_ID"))
        # Initialize discord bot
        intents = discord.Intents.default()
        intents.message_content = True
        intents.messages = True
        # Discord bot command prefix
        bot = commands.Bot(command_prefix="!", intents=intents)
        bot.remove_command("help")
        print()
        print("Discord bot is started...")
        print()

        # Initialize database connection
        async def init_db():
            bot.db = await aiosqlite.connect(DATABASE_NAME)
            await bot.db.execute(
                """
                CREATE TABLE IF NOT EXISTS rsa_credentials (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    broker TEXT NOT NULL,
                    credentials TEXT NOT NULL,
                    CONSTRAINT unique_user_broker UNIQUE (user_id, broker)
                )
            """
            )
            await bot.db.commit()

        async def ensure_db_connection():
            if not hasattr(bot, "db") or bot.db is None:
                await init_db()
            else:
                try:
                    await bot.db.execute("SELECT 1")
                except ValueError:
                    await init_db()

        # Bot event when bot is ready
        @bot.event
        async def on_ready():
            channel = bot.get_channel(DISCORD_CHANNEL)
            if channel is None:
                print(
                    "ERROR: Invalid channel ID, please check your DISCORD_CHANNEL in your .env file and try again"
                )
                os._exit(1)  # Special exit code to restart docker container

            await init_db()
            await channel.send("Discord bot is started...")

        @bot.event
        async def on_disconnect():
            if hasattr(bot, "db"):
                await bot.db.close()

        # Process the message only if it's from the specified channel
        @bot.event
        async def on_message(message):
            if (
                isinstance(message.channel, discord.DMChannel)
                or message.channel.id == DISCORD_CHANNEL
            ):
                await bot.process_commands(message)

        # Bot ping-pong
        @bot.command(name="ping")
        async def ping(ctx):
            print("ponged")
            await ctx.send("pong")

        # Help command
        @bot.command()
        @commands.has_any_role(
            RSA_BOT_ROLE_ID, RSA_ADMIN_ROLE_ID, RSA_MENTEE_ROLE_ID, RSAUTOMATION_ROLE_ID
        )
        async def helprsa(ctx):
            # String of available commands
            await ctx.send(
                """
eMoney RSA Bot:
Refer to this channel to get info on how to use the **RSA bot:** <#1280202509247320165>
                """
            )

        # Main RSA command
        @bot.command(name="rsa")
        @commands.has_any_role(
            RSA_BOT_ROLE_ID, RSA_MENTEE_ROLE_ID, RSAUTOMATION_ROLE_ID
        )
        async def rsa(ctx, *args):
            await ensure_db_connection()
            discOrdObj = await bot.loop.run_in_executor(None, argParser, args)
            event_loop = asyncio.get_event_loop()
            try:
                author_id = ctx.author.id
                # Validate order object
                discOrdObj.order_validate(preLogin=True)
                # Get holdings or complete transaction
                if discOrdObj.get_holdings():
                    # Run Holdings
                    await fun_run(
                        author_id,
                        discOrdObj,
                        ("_init", "_holdings"),
                        bot,
                        event_loop,
                    )

                else:
                    # Run Transaction
                    await fun_run(
                        author_id,
                        discOrdObj,
                        ("_init", "_transaction"),
                        bot,
                        event_loop,
                    )

            except Exception as err:
                print(traceback.format_exc())
                print(f"Error placing order: {err}")
                if ctx:
                    await ctx.send(f"Error placing order: {err}")

        # Restart command
        @bot.command(name="restart")
        @commands.has_role(RSA_ADMIN_ROLE_ID)
        async def restart(ctx):
            print("Restarting...")
            print()
            await ctx.send("Restarting...")
            await bot.close()
            if DOCKER_MODE:
                os._exit(0)  # Special exit code to restart docker container
            else:
                os.execv(sys.executable, [sys.executable] + sys.argv)

        @bot.command(name="rsaadd")
        async def rsaadd(ctx, broker=None, credentials=None):
            await ensure_db_connection()

            try:
                if not isinstance(ctx.channel, discord.DMChannel):
                    await ctx.send("This command can only be used via DM.")
                    return

                if not broker or not credentials:
                    raise commands.MissingRequiredArgument(param=None)

                broker = broker.lower()
                if broker not in SUPPORTED_BROKERS:
                    raise Exception(f"{broker} is not a supported broker")

                # Handle different broker-specific credential formats
                if broker == "fennel":
                    if "@" not in credentials or len(credentials.split(":")) != 1:
                        raise Exception(
                            "Invalid credentials. Just enter your email for Fennel."
                        )
                elif broker == "robinhood":
                    if len(credentials.split(":")) != 3:
                        raise Exception(
                            "Invalid credentials. Use this format for Robinhood: username:password:otp_or_totp_secret|NA"
                        )
                elif broker == "tradier":
                    if len(credentials.split(":")) != 1:
                        raise Exception(
                            "Invalid credentials. Just enter your Tradier access token."
                        )
                elif broker == "vanguard":
                    if len(credentials.split(":")) != 3:
                        raise Exception(
                            "Invalid credentials. Use this format: username:password:last4digits"
                        )
                elif broker == "webull":
                    if len(credentials.split(":")) != 4:
                        raise Exception(
                            "Invalid credentials. Use this format: username:password:device_id:trading_pin"
                        )
                else:
                    if len(credentials.split(":")) != 2:
                        raise Exception(
                            "Invalid credentials. Use this format: username:password"
                        )

                encrypted_credentials = cipher_suite.encrypt(
                    credentials.encode()
                ).decode()

                async with bot.db.execute(
                    """
                    INSERT INTO rsa_credentials (user_id, broker, credentials)
                    VALUES (?, ?, ?) ON CONFLICT (user_id, broker) DO UPDATE SET credentials = ? 
                    """,
                    (
                        str(ctx.author.id),
                        broker,
                        encrypted_credentials,
                        encrypted_credentials,
                    ),
                ) as cursor:
                    await bot.db.commit()

                await ctx.send(f"Successfully added {broker} account")

            except Exception as e:
                print(traceback.format_exc())
                await ctx.send(f"Error adding {broker} account: {e}")

        @bot.command(name="removersa")
        @commands.has_any_role(
            RSA_BOT_ROLE_ID, RSA_ADMIN_ROLE_ID, RSA_MENTEE_ROLE_ID, RSAUTOMATION_ROLE_ID
        )
        async def removersa(ctx, broker):
            await ensure_db_connection()
            try:
                broker = broker.lower()
                if broker not in SUPPORTED_BROKERS:
                    raise Exception(f"{broker} is not a supported broker")

                async with bot.db.execute(
                    """
                    DELETE FROM rsa_credentials WHERE user_id = ? AND broker = ?
                """,
                    (str(ctx.author.id), broker),
                ) as cursor:
                    if cursor.rowcount > 0:
                        await bot.db.commit()
                        await ctx.send(
                            f"Successfully removed <@{ctx.author.id}>'s account from {broker}."
                        )
                    else:
                        await ctx.send(
                            f"No account found for <@{ctx.author.id}> with {broker}."
                        )

            except commands.MissingRole:
                await ctx.send(
                    "To get access to the RSA bot, follow the instructions here: <#1280212428415570053>"
                )
            except Exception as e:
                print(traceback.format_exc())
                await ctx.send(f"Error retrieving accounts: {e}")

        @bot.command(name="accountrsa")
        @commands.has_role(RSA_ADMIN_ROLE_ID)
        async def accountrsa(ctx):
            await ensure_db_connection()
            try:
                accounts = []
                async with bot.db.execute(
                    """
                    SELECT broker FROM rsa_credentials WHERE user_id = ?
                """,
                    (str(ctx.author.id),),
                ) as cursor:
                    accounts = await cursor.fetchall()

                # # Check all supported brokers
                # for broker in SUPPORTED_BROKERS:
                #     broker_env_var = os.getenv(broker.upper())
                #     if broker_env_var:
                #         credentials = broker_env_var.split(',')
                #         accounts.append(f"{broker.capitalize()}: {', '.join([cred.split(':')[0] for cred in credentials])}")

                if accounts:
                    # Prepare the message
                    account_message = (
                        "Here are the accounts you have set up:\n" + "\n".join(accounts)
                    )

                    # Handle Discord's 2000 character limit
                    if len(account_message) > 2000:
                        # Split the message into chunks of less than 2000 characters
                        parts = [
                            account_message[i : i + 2000]
                            for i in range(0, len(account_message), 2000)
                        ]
                        for part in parts:
                            await ctx.send(part)
                    else:
                        await ctx.send(account_message)
                else:
                    await ctx.send("You haven't set up any accounts yet.")

            except commands.MissingRole:
                await ctx.send(
                    "To get access to the RSA bot, follow the instructions here: <#1280212428415570053>"
                )
            except Exception as e:
                print(traceback.format_exc())
                await ctx.send(f"Error retrieving accounts: {e}")

        # Catch bad commands
        @bot.event
        async def on_command_error(ctx, error):
            if not isinstance(error, discord.ext.commands.CommandNotFound):
                print(f"Command Error: {error}")
                await ctx.send(f"Command Error: {error}")
                # Print help command
                await ctx.send("Type '!helprsa' for a list of commands")

        # await bot.load_extension("slash_commands")

        # Run Discord bot
        async with bot:
            await bot.start(DISCORD_TOKEN)
            print("Discord bot is running...")
            # print()


if __name__ == "__main__":
    asyncio.run(main())
