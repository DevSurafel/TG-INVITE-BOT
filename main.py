import pymongo
import certifi
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.channels import JoinChannelRequest, InviteToChannelRequest
from telethon.tl.functions.contacts import GetContactsRequest
from telethon.tl.types import InputUser
from telethon.errors import FloodWaitError, ChannelPrivateError, UserAlreadyParticipantError, SessionPasswordNeededError, AuthKeyUnregisteredError
import asyncio
import random
import time
import json
from typing import List, Tuple, Set
from datetime import datetime, timedelta
from flask import Flask
import threading

# Flask app for Render (keeps the service alive)
app = Flask(__name__)

@app.route('/')
def home():
    return "Telegram Invite Bot is running!"

@app.route('/health')
def health():
    return {"status": "healthy", "last_run": get_last_run_info()}

def get_last_run_info():
    """Get information about the last run from MongoDB"""
    try:
        last_run = bot_state_collection.find_one({"_id": "last_run_info"})
        if last_run:
            return {
                "last_run": last_run.get("last_run", "Never"),
                "next_run": last_run.get("next_run", "Soon"),
                "success_count": last_run.get("success_count", 0),
                "failed_count": last_run.get("failed_count", 0),
                "total_time_minutes": last_run.get("total_time_minutes", 0)
            }
    except Exception as e:
        print(f"Error getting last run info: {e}")
    return {"last_run": "Never", "next_run": "Soon"}

def save_last_run_info(success_count, failed_count, total_time):
    """Save information about the last run to MongoDB"""
    try:
        next_run = datetime.now() + timedelta(hours=RUN_INTERVAL_HOURS)
        data = {
            "_id": "last_run_info",
            "last_run": datetime.now().isoformat(),
            "next_run": next_run.isoformat(),
            "success_count": success_count,
            "failed_count": failed_count,
            "total_time_minutes": round(total_time / 60, 2),
            "updated_at": datetime.now()
        }
        bot_state_collection.update_one(
            {"_id": "last_run_info"},
            {"$set": data},
            upsert=True
        )
        print(f"Saved last run info to MongoDB")
    except Exception as e:
        print(f"Error saving last run info: {e}")

# Replace these with your Telegram API credentials
API_ID = '20500952'
API_HASH = 'f429ad4a8b735edfa921f1cf6f7e3d0b'

# Group/Channel username (without @)
GROUP_USERNAME = "topcryptoinsider9"

# Scheduler Configuration
RUN_INTERVAL_HOURS = 10  # Run every 10 hours
AUTO_START = True  # Automatically start when deployed

# Session range configuration
START_SESSION = 401  # Start from session number (1-based) - Set to None to start from beginning
END_SESSION = None  # End at session number (1-based, inclusive) - Set to None to process all

# Concurrency settings
MAX_CONCURRENT_SESSIONS = 8  # Process 8 sessions simultaneously
BATCH_SIZE = 50  # Process sessions in batches
BATCH_DELAY_RANGE = (30, 60)  # Delay between batches (seconds)

# New Contact Sharing System Configuration
ENABLE_CONTACT_SHARING = True  # Enable cross-user contact sharing
MIN_CONTACTS_FOR_SHARING = 1000  # Users with 1000+ contacts can share
MAX_CONTACTS_TO_SHARE = 500    # Max contacts a user can share per session
CONTACT_SHARING_RATIO = 0.3    # Share 30% of contacts to low-contact users
LOW_CONTACT_THRESHOLD = 700    # Users with <700 contacts are considered "low contact"

# Contact invitation configuration
CONTACT_INVITE_BATCH_SIZE = 33  # Smaller batch size for invites to avoid flood limits
MAX_CONTACTS_TO_INVITE = 99    # Maximum contacts to invite per session (None for all)
DELAY_BETWEEN_INVITE_BATCHES = (15, 25)  # Delay between invite batches (seconds)

# MongoDB client setup with SSL and connection pooling
try:
    mongo_client = pymongo.MongoClient(
        "mongodb+srv://insurafel:cNkwKTx0tqajv1wg@telegram.kjlhc.mongodb.net/?retryWrites=true&w=majority&appName=telegram&tls=true",
        tlsCAFile=certifi.where(),
        maxPoolSize=100,  # Increased for concurrent connections
        connectTimeoutMS=30000,
        socketTimeoutMS=30000
    )
    db = mongo_client["telegram_sessions"]
    
    # Collections
    collection = db["sessions"]  # Original sessions collection
    invited_users_collection = db["invited_users"]  # Store invited users per session
    contact_pool_collection = db["contact_pool"]  # Shared contact pool
    bot_state_collection = db["bot_state"]  # Bot state and last run info
    
    # Create indexes for better performance
    invited_users_collection.create_index("session_id")
    contact_pool_collection.create_index("contact_id")
    
    print("Connected to MongoDB successfully!")
    print("Collections initialized: sessions, invited_users, contact_pool, bot_state")
except Exception as e:
    print(f"Failed to connect to MongoDB: {e}")
    raise

# Contact Manager Class for Sharing System (MongoDB-backed)
class ContactManager:
    def __init__(self):
        self.shared_contacts_pool = self.load_shared_contacts_pool()
    
    def load_shared_contacts_pool(self):
        """Load the shared contacts pool from MongoDB"""
        try:
            pool_doc = contact_pool_collection.find_one({"_id": "shared_pool"})
            if pool_doc:
                # Convert contributors list back to set
                contributors = set(pool_doc.get("contributors", []))
                contacts = pool_doc.get("contacts", [])
                last_updated = pool_doc.get("last_updated", 0)
                
                print(f"Loaded shared contact pool: {len(contacts)} contacts, {len(contributors)} contributors")
                return {
                    "contacts": contacts,
                    "contributors": contributors,
                    "last_updated": last_updated
                }
        except Exception as e:
            print(f"Error loading shared contacts pool from MongoDB: {e}")
        
        return {"contacts": [], "contributors": set(), "last_updated": 0}
    
    def save_shared_contacts_pool(self):
        """Save the shared contacts pool to MongoDB"""
        try:
            pool_data = {
                "_id": "shared_pool",
                "contacts": self.shared_contacts_pool["contacts"],
                "contributors": list(self.shared_contacts_pool["contributors"]),
                "last_updated": self.shared_contacts_pool["last_updated"],
                "updated_at": datetime.now()
            }
            
            contact_pool_collection.update_one(
                {"_id": "shared_pool"},
                {"$set": pool_data},
                upsert=True
            )
            print(f"Saved shared contact pool to MongoDB: {len(pool_data['contacts'])} contacts")
        except Exception as e:
            print(f"Error saving shared contacts pool to MongoDB: {e}")
    
    def contribute_to_pool(self, session_id, contacts, user_info):
        """High-contact users contribute contacts to the shared pool"""
        if not ENABLE_CONTACT_SHARING or len(contacts) < MIN_CONTACTS_FOR_SHARING:
            return 0
        
        # Don't contribute if already contributed
        if session_id in self.shared_contacts_pool.get("contributors", set()):
            print(f"[{user_info}] Already contributed to contact pool")
            return 0
        
        # Calculate how many contacts to share
        contacts_to_share = min(
            int(len(contacts) * CONTACT_SHARING_RATIO),
            MAX_CONTACTS_TO_SHARE
        )
        
        # Select random contacts to share (avoid duplicates)
        existing_contact_ids = {c.get("id") for c in self.shared_contacts_pool.get("contacts", [])}
        
        new_contacts = []
        available_contacts = [c for c in contacts if c.id not in existing_contact_ids]
        
        if available_contacts:
            selected_contacts = random.sample(
                available_contacts, 
                min(contacts_to_share, len(available_contacts))
            )
            
            for contact in selected_contacts:
                contact_data = {
                    "id": contact.id,
                    "access_hash": contact.access_hash,
                    "first_name": getattr(contact, 'first_name', ''),
                    "last_name": getattr(contact, 'last_name', ''),
                    "username": getattr(contact, 'username', ''),
                    "contributor": session_id
                }
                new_contacts.append(contact_data)
        
        # Add to pool
        if "contacts" not in self.shared_contacts_pool:
            self.shared_contacts_pool["contacts"] = []
        if "contributors" not in self.shared_contacts_pool:
            self.shared_contacts_pool["contributors"] = set()
        
        self.shared_contacts_pool["contacts"].extend(new_contacts)
        self.shared_contacts_pool["contributors"].add(session_id)
        self.shared_contacts_pool["last_updated"] = int(time.time())
        
        self.save_shared_contacts_pool()
        
        print(f"[{user_info}] Contributed {len(new_contacts)} contacts to shared pool")
        print(f"[{user_info}] Total contacts in pool: {len(self.shared_contacts_pool['contacts'])}")
        
        return len(new_contacts)
    
    def get_contacts_for_low_contact_user(self, session_id, user_contacts, user_info, max_contacts=200):
        """Get additional contacts for users with few contacts"""
        if not ENABLE_CONTACT_SHARING:
            return []
        
        # Check if user qualifies for contact sharing
        if len(user_contacts) >= LOW_CONTACT_THRESHOLD:
            return []
        
        pool_contacts = self.shared_contacts_pool.get("contacts", [])
        if not pool_contacts:
            print(f"[{user_info}] No contacts available in shared pool")
            return []
        
        # Get user's existing contact IDs to avoid duplicates
        user_contact_ids = {contact.id for contact in user_contacts}
        
        # Filter out contacts the user already has and contacts they contributed
        available_contacts = [
            c for c in pool_contacts 
            if c["id"] not in user_contact_ids and c.get("contributor") != session_id
        ]
        
        if not available_contacts:
            print(f"[{user_info}] No new contacts available from shared pool")
            return []
        
        # Randomly select contacts to give to this user
        contacts_to_give = min(max_contacts, len(available_contacts))
        selected_contacts = random.sample(available_contacts, contacts_to_give)
        
        # Convert back to contact-like objects
        shared_contacts = []
        for contact_data in selected_contacts:
            # Create a simple object with the necessary attributes
            class SharedContact:
                def __init__(self, data):
                    self.id = data["id"]
                    self.access_hash = data["access_hash"]
                    self.first_name = data.get("first_name", "")
                    self.last_name = data.get("last_name", "")
                    self.username = data.get("username", "")
                    self.bot = False  # Assume shared contacts are not bots
            
            shared_contacts.append(SharedContact(contact_data))
        
        print(f"[{user_info}] Received {len(shared_contacts)} contacts from shared pool")
        return shared_contacts

# Initialize the contact manager
contact_manager = ContactManager()

async def join_group(client, group_username):
    """Join a Telegram group/channel"""
    try:
        # Handle different link formats
        if group_username.startswith("https://t.me/+"):
            # Extract hash from private link and convert to joinchat format
            hash_part = group_username.replace("https://t.me/+", "")
            group_link = f"https://t.me/joinchat/{hash_part}"
            group = await client.get_entity(group_link)
        elif group_username.startswith("https://t.me/joinchat/"):
            # Direct joinchat link
            group = await client.get_entity(group_username)
        elif group_username.startswith("joinchat/"):
            # joinchat format without full URL
            group = await client.get_entity(f"https://t.me/{group_username}")
        else:
            # Regular username or public link
            group = await client.get_entity(group_username)
        
        # Join the group
        await client(JoinChannelRequest(group))
        print(f"Successfully joined {group_username}!")
        return group
        
    except UserAlreadyParticipantError:
        print(f"Already a member of {group_username}")
        # Try to get entity again for already joined groups
        if group_username.startswith("https://t.me/+"):
            hash_part = group_username.replace("https://t.me/+", "")
            group_link = f"https://t.me/joinchat/{hash_part}"
            group = await client.get_entity(group_link)
        elif group_username.startswith("https://t.me/joinchat/"):
            group = await client.get_entity(group_username)
        elif group_username.startswith("joinchat/"):
            group = await client.get_entity(f"https://t.me/{group_username}")
        else:
            group = await client.get_entity(group_username)
        return group
    except ChannelPrivateError:
        print(f"Cannot join {group_username}: Channel is private")
        return None
    except Exception as e:
        print(f"Error joining group {group_username}: {e}")
        return None

async def get_contacts_with_sharing(client, user_info, session_id):
    """Enhanced contact retrieval with sharing mechanism"""
    try:
        # Get user's own contacts first
        result = await client(GetContactsRequest(hash=0))
        own_contacts = result.users
        own_contact_count = len(own_contacts)
        
        print(f"[{user_info}] Retrieved {own_contact_count} own contacts")
        
        # If user has many contacts, contribute to shared pool
        if own_contact_count >= MIN_CONTACTS_FOR_SHARING:
            contributed = contact_manager.contribute_to_pool(session_id, own_contacts, user_info)
            print(f"[{user_info}] High-contact user - contributed {contributed} contacts to pool")
            return own_contacts
        
        # If user has few contacts, get additional from shared pool
        elif own_contact_count < LOW_CONTACT_THRESHOLD:
            shared_contacts = contact_manager.get_contacts_for_low_contact_user(
                session_id, own_contacts, user_info, max_contacts=200
            )
            
            # Combine own contacts with shared contacts
            all_contacts = own_contacts + shared_contacts
            total_count = len(all_contacts)
            
            print(f"[{user_info}] Low-contact user - total contacts: {total_count} (own: {own_contact_count}, shared: {len(shared_contacts)})")
            return all_contacts
        
        else:
            # Medium contact count - use own contacts
            print(f"[{user_info}] Medium-contact user - using own contacts")
            return own_contacts
            
    except Exception as e:
        print(f"[{user_info}] Error retrieving contacts: {e}")
        return []

async def load_invited_users(session_id):
    """Load previously invited user IDs from MongoDB for a specific session"""
    try:
        doc = invited_users_collection.find_one({"session_id": session_id})
        if doc and "invited_user_ids" in doc:
            invited_set = set(doc["invited_user_ids"])
            print(f"Loaded {len(invited_set)} previously invited users for session {session_id}")
            return invited_set
    except Exception as e:
        print(f"Error loading invited users from MongoDB: {e}")
    return set()

async def save_invited_users(session_id, invited_users):
    """Save invited user IDs to MongoDB for a specific session"""
    try:
        invited_users_collection.update_one(
            {"session_id": session_id},
            {
                "$set": {
                    "session_id": session_id,
                    "invited_user_ids": list(invited_users),
                    "updated_at": datetime.now()
                }
            },
            upsert=True
        )
        print(f"Saved {len(invited_users)} invited users to MongoDB for session {session_id}")
    except Exception as e:
        print(f"Error saving invited users to MongoDB: {e}")

async def add_contacts_to_group(client, group, contacts, user_info, session_id):
    """Add contacts to the specified group in batches with flood protection"""
    if not contacts:
        print(f"[{user_info}] No contacts available")
        return 0, 0, []
    
    # Load previously invited users for this session
    invited_users = await load_invited_users(session_id)
    total_invited = 0
    total_failed = 0
    invite_logs = []
    
    # Filter valid contacts and exclude already invited users
    valid_contacts = [
        contact for contact in contacts
        if hasattr(contact, 'id') and hasattr(contact, 'access_hash') and contact.access_hash is not None
        and contact.id not in invited_users and not contact.bot
    ]
    
    # Limit contacts if MAX_CONTACTS_TO_INVITE is set
    if MAX_CONTACTS_TO_INVITE and len(valid_contacts) > MAX_CONTACTS_TO_INVITE:
        valid_contacts = valid_contacts[:MAX_CONTACTS_TO_INVITE]
    
    print(f"[{user_info}] Found {len(valid_contacts)} valid contacts to invite")
    
    if not valid_contacts:
        print(f"[{user_info}] No valid contacts to add")
        return 0, 0, ["No valid contacts to invite"]
    
    # Process contacts in batches
    for i in range(0, len(valid_contacts), CONTACT_INVITE_BATCH_SIZE):
        batch = valid_contacts[i:i + CONTACT_INVITE_BATCH_SIZE]
        input_users = [
            InputUser(user_id=contact.id, access_hash=contact.access_hash)
            for contact in batch
        ]
        
        batch_invited = 0
        batch_failed = 0
        
        try:
            # Invite the batch of users to the group
            await client(InviteToChannelRequest(
                channel=group,
                users=input_users
            ))
            batch_invited = len(batch)
            total_invited += batch_invited
            
            # Update invited users and save progress
            for contact in batch:
                invited_users.add(contact.id)
            await save_invited_users(session_id, invited_users)
            
            print(f"[{user_info}] Successfully invited {batch_invited} users (Total: {total_invited})")
            invite_logs.append(f"Invited batch of {batch_invited} users")
            
        except FloodWaitError as e:
            print(f"[{user_info}] Flood wait error for invites: Need to wait {e.seconds} seconds")
            invite_logs.append(f"Hit flood wait: {e.seconds}s - stopping invites for this session")
            
            # Save progress and break - we'll continue from here next time
            await save_invited_users(session_id, invited_users)
            break
            
        except UserAlreadyParticipantError:
            print(f"[{user_info}] Some users in invite batch are already in the group")
            # Still mark as invited to avoid retrying
            batch_invited = len(batch)
            total_invited += batch_invited
            for contact in batch:
                invited_users.add(contact.id)
            await save_invited_users(session_id, invited_users)
            invite_logs.append(f"Batch of {batch_invited} users already in group")
            
        except Exception as e:
            print(f"[{user_info}] Error inviting batch: {e}")
            batch_failed = len(batch)
            total_failed += batch_failed
            invite_logs.append(f"Failed to invite batch: {str(e)[:50]}")
        
        # Delay between invite batches
        if i + CONTACT_INVITE_BATCH_SIZE < len(valid_contacts):
            delay = random.uniform(*DELAY_BETWEEN_INVITE_BATCHES)
            await asyncio.sleep(delay)
    
    print(f"[{user_info}] Contact invites finished - Invited: {total_invited}, Failed: {total_failed}")
    return total_invited, total_failed, invite_logs

async def process_session(session_data: Tuple[str, str, int]) -> Tuple[bool, str]:
    """Process a single session - returns (success, session_info)"""
    session_string, session_id, session_index = session_data
    client = None
    
    try:
        # Create client for this session
        client = TelegramClient(StringSession(session_string), API_ID, API_HASH)
        
        # Connect to Telegram
        await client.connect()
        
        # Check if the user is authorized
        if not await client.is_user_authorized():
            return False, f"Session {session_index} - Login failed (invalid session)"
        
        # Get user info for logging
        me = await client.get_me()
        user_info = f"Session {session_index} - {me.first_name or 'Unknown'}"
        
        print(f"[{user_info}] Logged in successfully!")
        
        # Join the group
        group = await join_group(client, GROUP_USERNAME)
        
        if group:
            # Wait a bit after joining before processing
            delay = random.randint(3, 15)
            print(f"[{user_info}] Waiting {delay} seconds after joining...")
            await asyncio.sleep(delay)
            
            # Initialize results
            result_messages = []
            
            # Add contacts to group with enhanced sharing
            print(f"[{user_info}] Starting contact invitations...")
            contacts = await get_contacts_with_sharing(client, user_info, session_id)
            invited_count, failed_count, invite_logs = await add_contacts_to_group(
                client, group, contacts, user_info, session_id
            )
            
            if invited_count > 0:
                result_messages.append(f"Invited {invited_count} contacts")
            if failed_count > 0:
                result_messages.append(f"Failed to invite {failed_count} contacts")
            
            # Determine overall success
            overall_success = invited_count > 0
            final_message = f"{user_info} - " + " | ".join(result_messages) if result_messages else f"{user_info} - No contacts invited"
            
            return overall_success, final_message
        else:
            return False, f"{user_info} - Failed to join group"
        
    except SessionPasswordNeededError:
        return False, f"Session {session_index} - 2FA enabled, skipping"
    except AuthKeyUnregisteredError:
        return False, f"Session {session_index} - Invalid/expired session"
    except FloodWaitError as e:
        print(f"[Session {session_index}] Global flood wait: {e.seconds} seconds")
        await asyncio.sleep(e.seconds + random.randint(15, 30))
        return False, f"Session {session_index} - Hit flood wait, retrying later"
    except Exception as e:
        return False, f"Session {session_index} - Error: {str(e)[:100]}"
    finally:
        if client:
            try:
                await client.disconnect()
            except:
                pass

async def process_batch_concurrent(session_batch: List[Tuple[str, str, int]]) -> Tuple[int, int, List[str]]:
    """Process a batch of sessions concurrently"""
    print(f"\n=== Processing batch of {len(session_batch)} sessions concurrently ===")
    
    # Create semaphore to limit concurrent sessions
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_SESSIONS)
    
    async def process_with_semaphore(session_data):
        async with semaphore:
            # Add small random delay to stagger session starts
            await asyncio.sleep(random.uniform(0.5, 3.0))
            return await process_session(session_data)
    
    # Process all sessions in the batch concurrently
    start_time = time.time()
    results = await asyncio.gather(*[process_with_semaphore(session_data) for session_data in session_batch], return_exceptions=True)
    end_time = time.time()
    
    # Count results
    successful = 0
    failed = 0
    logs = []
    
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            failed += 1
            logs.append(f"Session {session_batch[i][2]} - Exception: {str(result)[:100]}")
        else:
            success, message = result
            if success:
                successful += 1
            else:
                failed += 1
            logs.append(message)
    
    batch_time = end_time - start_time
    print(f"Batch completed in {batch_time:.1f}s - Success: {successful}, Failed: {failed}")
    
    return successful, failed, logs

async def run_invite_cycle():
    """Main function to process all sessions from MongoDB with concurrent processing"""
    try:
        print(f"\n{'='*80}")
        print(f"STARTING NEW INVITE CYCLE - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*80}\n")
        
        # Get all sessions from MongoDB
        sessions = collection.find({}, {"session_string": 1, "_id": 1})
        sessions_list = list(sessions)
        
        if not sessions_list:
            print("No sessions found in MongoDB")
            return
        
        total_sessions = len(sessions_list)
        print(f"Found {total_sessions} total sessions in MongoDB")
        
        # Apply session range filtering
        if START_SESSION is not None and END_SESSION is not None:
            # Convert to 0-based indexing
            start_idx = max(0, START_SESSION - 1)
            end_idx = min(total_sessions, END_SESSION)
            
            # Validate range
            if start_idx >= total_sessions:
                print(f"Start session {START_SESSION} is beyond available sessions ({total_sessions})")
                return
            
            # Slice the sessions list
            sessions_list = sessions_list[start_idx:end_idx]
            print(f"Processing sessions {START_SESSION} to {min(END_SESSION, total_sessions)} ({len(sessions_list)} sessions)")
        elif START_SESSION is not None:
            # Only start session specified
            start_idx = max(0, START_SESSION - 1)
            if start_idx >= total_sessions:
                print(f"Start session {START_SESSION} is beyond available sessions ({total_sessions})")
                return
            sessions_list = sessions_list[start_idx:]
            print(f"Processing sessions {START_SESSION} to {total_sessions} ({len(sessions_list)} sessions)")
        elif END_SESSION is not None:
            # Only end session specified
            end_idx = min(total_sessions, END_SESSION)
            sessions_list = sessions_list[:end_idx]
            print(f"Processing sessions 1 to {END_SESSION} ({len(sessions_list)} sessions)")
        else:
            print(f"Processing all {len(sessions_list)} sessions")
        
        print(f"Processing with {MAX_CONCURRENT_SESSIONS} concurrent sessions per batch")
        print(f"Batch size: {BATCH_SIZE} sessions")
        
        # Prepare session data with indices
        session_data = []
        start_idx = START_SESSION - 1 if START_SESSION else 0
        
        for i, session_doc in enumerate(sessions_list, 1):
            session_string = session_doc.get("session_string")
            session_id = str(session_doc.get("_id"))
            
            # Calculate actual session number for display
            actual_session_num = start_idx + i
            
            if session_string:
                session_data.append((session_string, session_id, actual_session_num))
            else:
                print(f"[Session {actual_session_num}] No session string found, skipping...")
        
        print(f"Valid sessions to process: {len(session_data)}")
        
        if not session_data:
            print("No valid sessions to process")
            return
        
        # Split into batches
        batches = [session_data[i:i + BATCH_SIZE] for i in range(0, len(session_data), BATCH_SIZE)]
        
        # Statistics
        total_successful = 0
        total_failed = 0
        all_logs = []
        
        print(f"\nStarting processing of {len(batches)} batches...")
        overall_start_time = time.time()
        
        for batch_num, batch in enumerate(batches, 1):
            print(f"\n{'='*60}")
            print(f"BATCH {batch_num}/{len(batches)}")
            print(f"Sessions {batch[0][2]} to {batch[-1][2]}")
            print(f"{'='*60}")
            
            # Process the batch
            batch_successful, batch_failed, batch_logs = await process_batch_concurrent(batch)
            
            # Update totals
            total_successful += batch_successful
            total_failed += batch_failed
            all_logs.extend(batch_logs)
            
            # Progress update
            processed_so_far = batch_num * BATCH_SIZE
            if processed_so_far > len(session_data):
                processed_so_far = len(session_data)
            
            progress = (processed_so_far / len(session_data)) * 100
            print(f"\nProgress: {processed_so_far}/{len(session_data)} ({progress:.1f}%)")
            print(f"Running totals - Success: {total_successful}, Failed: {total_failed}")
            
            # Display session range being processed
            session_range = f"({session_data[0][2]} to {session_data[-1][2]})" if session_data else ""
            print(f"Session range in this run: {session_range}")
            
            # Delay between batches (except for the last batch)
            if batch_num < len(batches):
                delay = random.randint(*BATCH_DELAY_RANGE)
                print(f"Waiting {delay} seconds before next batch...")
                await asyncio.sleep(delay)
        
        overall_end_time = time.time()
        total_time = overall_end_time - overall_start_time
        
        # Final summary
        range_info = ""
        if START_SESSION is not None and END_SESSION is not None:
            range_info = f"Sessions {START_SESSION}-{END_SESSION}"
        elif START_SESSION is not None:
            range_info = f"Sessions {START_SESSION}-{total_sessions}"
        elif END_SESSION is not None:
            range_info = f"Sessions 1-{END_SESSION}"
        else:
            range_info = "All sessions"
            
        print(f"\n{'='*80}")
        print(f"CYCLE COMPLETED - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*80}")
        print(f"Total sessions in database: {total_sessions}")
        print(f"Sessions processed: {len(session_data)}")
        print(f"Successful operations: {total_successful}")
        print(f"Failed sessions: {total_failed}")
        if len(session_data) > 0:
            print(f"Success rate: {(total_successful/len(session_data)*100):.1f}%")
        print(f"Total processing time: {total_time/3600:.2f} hours ({total_time/60:.1f} minutes)")
        if len(session_data) > 0:
            print(f"Average time per session: {total_time/len(session_data):.2f} seconds")
            print(f"Sessions per minute: {len(session_data)/(total_time/60):.1f}")
        
        # Show contact sharing statistics
        if ENABLE_CONTACT_SHARING:
            pool_size = len(contact_manager.shared_contacts_pool.get("contacts", []))
            contributors = len(contact_manager.shared_contacts_pool.get("contributors", set()))
            print(f"\nContact Sharing Statistics:")
            print(f"- Total contacts in shared pool: {pool_size}")
            print(f"- Contributing sessions: {contributors}")
        
        # Save last run info to MongoDB
        save_last_run_info(total_successful, total_failed, total_time)
        
        print(f"\n{'='*80}")
        print(f"NEXT RUN SCHEDULED IN {RUN_INTERVAL_HOURS} HOURS")
        print(f"Next run: {(datetime.now() + timedelta(hours=RUN_INTERVAL_HOURS)).strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*80}\n")
        
    except Exception as e:
        print(f"Error in invite cycle: {e}")
        import traceback
        traceback.print_exc()

async def scheduler_loop():
    """Continuously run invite cycles every RUN_INTERVAL_HOURS"""
    print(f"Scheduler started - will run every {RUN_INTERVAL_HOURS} hours")
    
    while True:
        try:
            # Run the invite cycle
            await run_invite_cycle()
            
            # Wait for the specified interval before next run
            wait_seconds = RUN_INTERVAL_HOURS * 3600
            print(f"Waiting {RUN_INTERVAL_HOURS} hours until next cycle...")
            await asyncio.sleep(wait_seconds)
            
        except Exception as e:
            print(f"Error in scheduler loop: {e}")
            print("Retrying in 5 minutes...")
            await asyncio.sleep(300)  # Wait 5 minutes before retry

def run_flask():
    """Run Flask server in a separate thread"""
    import os
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

def main():
    """Main entry point"""
    print("="*80)
    print("TELEGRAM CONTACT INVITE BOT - AUTOMATIC SCHEDULER")
    print("WITH MONGODB PERSISTENT STORAGE")
    print("="*80)
    print(f"Configuration:")
    print(f"- Run interval: Every {RUN_INTERVAL_HOURS} hours")
    print(f"- Auto-start: {AUTO_START}")
    print(f"- Max concurrent sessions: {MAX_CONCURRENT_SESSIONS}")
    print(f"- Batch size: {BATCH_SIZE}")
    print(f"- Target group: {GROUP_USERNAME}")
    print(f"- Storage: MongoDB (Persistent across restarts)")
    print(f"\n⚠️  IMPORTANT SAFETY NOTES:")
    print(f"- Your session strings are READ-ONLY (never modified)")
    print(f"- Only NEW collections are created: invited_users, contact_pool, bot_state")
    print(f"- Original 'sessions' collection remains untouched")
    print(f"- Bot will run automatically every {RUN_INTERVAL_HOURS} hours (24/7)")
    
    if ENABLE_CONTACT_SHARING:
        print(f"\n- Contact sharing: Enabled")
        print(f"- High contact threshold: {MIN_CONTACTS_FOR_SHARING}")
        print(f"- Low contact threshold: {LOW_CONTACT_THRESHOLD}")
    
    print(f"- Contact invite batch size: {CONTACT_INVITE_BATCH_SIZE}")
    print(f"- Max contacts per session: {MAX_CONTACTS_TO_INVITE if MAX_CONTACTS_TO_INVITE else 'All'}")
    
    if START_SESSION is not None and END_SESSION is not None:
        print(f"- Session range: {START_SESSION} to {END_SESSION}")
    elif START_SESSION is not None:
        print(f"- Session range: {START_SESSION} to end")
    elif END_SESSION is not None:
        print(f"- Session range: 1 to {END_SESSION}")
    else:
        print(f"- Session range: All sessions")
    
    print("="*80)
    
    # Start Flask server in a separate thread
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    print("✅ Flask server started for Render health checks")
    print("✅ Bot will keep running indefinitely (Render won't sleep it)")
    print("✅ Automatic restart protection: If Render restarts, scheduler resumes automatically")
    
    # Start the scheduler
    try:
        asyncio.run(scheduler_loop())
    except KeyboardInterrupt:
        print("\n⚠️  Shutting down gracefully...")
        mongo_client.close()
        print("✅ MongoDB connection closed")
    except Exception as e:
        print(f"❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        mongo_client.close()

if __name__ == '__main__':
    main()
