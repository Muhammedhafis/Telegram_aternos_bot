import os
import json
import aiohttp
import time
import logging
from logging.handlers import TimedRotatingFileHandler

from telegram import Update
from telegram.ext import Application, CommandHandler, CallbackContext

import dotenv
import python_aternos

dotenv.load_dotenv()

fP = os.path.dirname(os.path.realpath(__file__))
sP = os.path.dirname(os.path.realpath(__file__)) + "/sessions/{username}.aternos"
if not 'logs' in os.listdir(fP): os.mkdir(f"{fP}/logs")
if not 'sessions' in os.listdir(fP): os.mkdir(f"{fP}/sessions")
if not 'uconfig.json' in os.listdir(fP):
    with open('uconfig.json', 'w') as f:
        json.dump({"guilds": {}, "users": {}}, f, indent=2)

logging.basicConfig(
    format='%(asctime)s %(levelname)-8s %(message)s',
    level=logging.DEBUG,
    datefmt='%Y-%m-%d %H:%M:%S'
)
handler = TimedRotatingFileHandler(f"{fP}/logs/acs.log", when="midnight", interval=1)
handler.suffix = "%Y%m%d"
formatter = logging.Formatter("%(asctime)s %(levelname)-8s %(message)s")
handler.setFormatter(formatter)
logger = logging.getLogger(__name__)
logger.addHandler(handler)

def get_config():
    with open(f'{fP}/uconfig.json', 'r', encoding='utf-8') as f:
        c = json.load(f)
    return c

def save_config(cfg):
    with open(f'{fP}/uconfig.json', 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

def update_user(user_id, username: str=None, servers: list=None):
    config = get_config()
    u = config['users'].get(str(user_id))

    if u:
        username = username or u.get('username')
        servers = servers or u.get('servers')

    user = {
        "username": username,
        "servers": servers or []
    }
    config['users'][user_id] = user

    save_config(config)

async def start(update: Update, context: CallbackContext):
    await update.message.reply_text('Bot started. Use /login to authenticate.')

async def login(update: Update, context: CallbackContext):
    if len(context.args) != 2:
        await update.message.reply_text('Usage: /login <username> <password>')
        return

    username, password = context.args
    try:
        aclient = python_aternos.Client.from_credentials(username, password)
    except python_aternos.CredentialsError:
        await update.message.reply_text('Invalid username or password. Please check and retry.')
        return

    config = get_config()
    uid = str(update.message.from_user.id)
    gid = str(update.message.chat.id)
    if not config['guilds'].get(gid):
        config['guilds'][gid] = {"logged_users": []}
    config['guilds'][gid]['logged_users'].append(uid)
    save_config(config)
    update_user(uid, username=username, servers=[s.domain for s in aclient.list_servers()])
    aclient.save_session(file=sP.format(username=username))
    await update.message.reply_text('Successfully logged in!')

async def list_servers(update: Update, context: CallbackContext):
    gid = str(update.message.chat.id)
    uid = str(update.message.from_user.id)

    config = get_config()
    msg = "List of all Aternos servers available:\n"

    if config['guilds'].get(gid):
        for user in config['guilds'][gid]['logged_users']:
            cfg_user = config['users'].get(str(user))
            if cfg_user:
                auser = python_aternos.Client.restore_session(file=sP.format(username=cfg_user['username']))
                update_user(user, servers=[s.domain for s in auser.list_servers()])
                for server in auser.list_servers():
                    msg += f"- `{server.address}`, {server.version}\n"
    else:
        msg = "❌ No available Aternos servers in this chat!"

    await update.message.reply_text(msg)

async def set_default(update: Update, context: CallbackContext):
    if len(context.args) != 1:
        await update.message.reply_text('Usage: /setdefault <server_ip>')
        return

    server_ip = context.args[0]
    gid = str(update.message.chat.id)
    config = get_config()

    if not config['guilds'].get(gid):
        config['guilds'][gid] = {"logged_users": []}
    config['guilds'][gid]['default'] = server_ip
    save_config(config)
    await update.message.reply_text(f"✅ `{server_ip}` is now set as your chat default Minecraft server!")

async def status(update: Update, context: CallbackContext):
    if len(context.args) < 1:
        await update.message.reply_text('Usage: /status <server_ip> [port]')
        return

    server_ip = context.args[0]
    port = int(context.args[1]) if len(context.args) > 1 else 46390
    gid = str(update.message.chat.id)

    if server_ip == "default":
        config = get_config()
        guild = config['guilds'].get(gid)
        if guild:
            server_ip = guild.get('default')
            if not server_ip:
                await update.message.reply_text("❌ No default server IP configured. Use /setdefault to set one.")
                return
        else:
            await update.message.reply_text("❌ No default server IP configured. Use /setdefault to set one.")
            return

    async with aiohttp.ClientSession() as s:
        async with s.get("https://mcapi.us/server/status", params={"ip": server_ip, "port": port}) as r:
            res = json.loads(await r.text())

            if res['status'] != "success":
                msg = f"❌ There was an error.\n> {res['error']}"
                if int(res['last_updated']) + 60*5 > time.time():
                    msg += "\n\n*/!\\ Be aware that the results are from less than 5 minutes ago, and thus might not be up to date!*"
            else:
                if res['players']['max'] == 0:
                    if "Server not found" in res['motd']:
                        msg = "❌ This Aternos server was not found."
                    elif "This server is offline" in res['motd']:
                        msg = "❌ This Aternos server is offline."
                else:
                    if not res['online']:
                        msg = "❌ This server is offline"
                    else:
                        sname = ''.join(char for i, char in enumerate(res['motd']) if char != "§" and (i == 0 or res['motd'][i-1] != "§"))
                        msg = f"✅ **{sname}** is online!"
                        if res['players']['now'] > 0:
                            if res['players']['max'] == res['players']['now']:
                                msg += f"\n\nUnfortunately, the maximum number of {res['players']['max']} players has been reached.."
                            else:
                                msg += f"\n\nJoin the {res['players']['now']} current player{'s' if res['players']['now'] > 1 else ''}!"
                                msg += f"\n> ip: `{server_ip}`\n> version: `{res['server']['name']}`"

    await update.message.reply_text(msg)

async def turn_on(update: Update, context: CallbackContext):
    if len(context.args) < 1:
        await update.message.reply_text('Usage: /turnon <server_ip>')
        return

    server_ip = context.args[0]
    gid = str(update.message.chat.id)

    if server_ip == "default":
        config = get_config()
        guild = config['guilds'].get(gid)
        if guild:
            server_ip = guild.get('default')
            if not server_ip:
                await update.message.reply_text("❌ No default server IP configured. Use /setdefault to set one.")
                return
        else:
            await update.message.reply_text("❌ No default server IP configured. Use /setdefault to set one.")
            return

    config = get_config()
    for user in config['guilds'][gid]['logged_users']:
        if server_ip in config['users'][user]['servers']:
            aclient = python_aternos.Client.restore_session(file=sP.format(username=config['users'][user]['username']))
            servers = aclient.list_servers()
            for server in servers:
                if server.address == server_ip or server.domain == server_ip:
                    try:
                        server.start()
                        await update.message.reply_text("✅ Server was successfully started! It should be up in 1 to 2 minutes.")
                    except Exception as e:
                        await update.message.reply_text(f"❌ Failed to start the server. Error: {e}")
                    return
    await update.message.reply_text("❌ No matching server found in your sessions.")

async def turn_off(update: Update, context: CallbackContext):
    if len(context.args) < 1:
        await update.message.reply_text('Usage: /turnoff <server_ip>')
        return

    server_ip = context.args[0]
    gid = str(update.message.chat.id)

    if server_ip == "default":
        config = get_config()
        guild = config['guilds'].get(gid)
        if guild:
            server_ip = guild.get('default')
            if not server_ip:
                await update.message.reply_text("❌ No default server IP configured. Use /setdefault to set one.")
                return
        else:
            await update.message.reply_text("❌ No default server IP configured. Use /setdefault to set one.")
            return

    config = get_config()
    for user in config['guilds'][gid]['logged_users']:
        if server_ip in config['users'][user]['servers']:
            aclient = python_aternos.Client.restore_session(file=sP.format(username=config['users'][user]['username']))
            servers = aclient.list_servers()
            for server in servers:
                if server.address == server_ip or server.domain == server_ip:
                    try:
                        server.stop()
                        await update.message.reply_text("✅ Server was successfully stopped!")
                    except Exception as e:
                        await update.message.reply_text(f"❌ Failed to stop the server. Error: {e}")
                    return
    await update.message.reply_text("❌ No matching server found in your sessions.")

def main():
    API_KEY = os.getenv('TELEGRAM_API_KEY')
    if not API_KEY:
        raise ValueError("TELEGRAM_API_KEY is not set in environment variables.")
    
    application = Application.builder().token(API_KEY).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("login", login))
    application.add_handler(CommandHandler("listservers", list_servers))
    application.add_handler(CommandHandler("setdefault", set_default))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("turnon", turn_on))
    application.add_handler(CommandHandler("turnoff", turn_off))

    application.run_polling()

if __name__ == '__main__':
    main()