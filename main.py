from telethon import TelegramClient, events, errors
import asyncio
from telethon.tl.types import InputMessagesFilterVideo
import logging

# Your API credentials (list of dictionaries with API details)
api_credentials = [
    {
        'api_id': 28170741,
        'api_hash': '0f04efb7ef30a5f565eb540483729548',
        'phone_number': '+94 77 015 2585'
    },    {
        'api_id': 25739668,
        'api_hash': '6015dc83d678b292e362253341c9e585',
        'phone_number': '+94740294247'
    },
    # Add more API credentials for other users if needed
]

# Initialize logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Dictionary to store session information for each user (user's phone number is the key)
users_data = {}

# Set to store already forwarded video file IDs (to prevent duplicates)
forwarded_video_file_ids = set()

# Helper function to load forwarded video file IDs from a text file
def load_forwarded_video_file_ids():
    try:
        with open("forwarded_video_file_ids.txt", "r") as f:
            return set(line.strip() for line in f if line.strip())
    except FileNotFoundError:
        return set()

# Helper function to save forwarded video file IDs to a text file
def save_forwarded_video_file_ids():
    with open("forwarded_video_file_ids.txt", "w") as f:
        for file_id in forwarded_video_file_ids:
            f.write(f"{file_id}\n")

# Load forwarded video file IDs on bot startup
forwarded_video_file_ids = load_forwarded_video_file_ids()

# Helper function to handle user commands
async def handle_user_message(event, phone_number):
    global users_data

    if phone_number not in users_data:
        users_data[phone_number] = {
            'source_chat_link': None,
            'target_chat': None,
            'skip_wait': False
        }

    user_data = users_data[phone_number]
    message_text = event.raw_text.strip()

    if message_text.startswith('/settarget'):
        try:
            new_target_chat = message_text.split(' ', 1)[1].strip()
            user_data['target_chat'] = new_target_chat
            await event.reply(f"Target chat updated to: {new_target_chat}")
        except IndexError:
            await event.reply("Usage: /settarget <chat_username_or_ID>")
        return

    if message_text.startswith('/setsource'):
        try:
            user_data['source_chat_link'] = message_text.split(' ', 1)[1].strip()
            await event.reply(f"Source chat set to: {user_data['source_chat_link']}")
        except IndexError:
            await event.reply("Usage: /setsource <chat_username_or_ID>")
        return

    if message_text == '/list':
        await event.reply(
            f"Source chat: {user_data['source_chat_link'] or 'Not set'}\n"
            f"Target chat: {user_data['target_chat'] or 'Not set'}"
        )
        return

    if message_text == '/boost':
        if not user_data['source_chat_link'] or not user_data['target_chat']:
            await event.reply("Please set both source and target chats first using /setsource and /settarget.")
        else:
            await event.reply(f"Boost mode activated! Forwarding videos from {user_data['source_chat_link']} to {user_data['target_chat']}...")
            await forward_videos_from_source(event.client, user_data['source_chat_link'], user_data['target_chat'], boost=True, phone_number=phone_number)
        return

    if message_text == '/startforward':
        if not user_data['source_chat_link'] or not user_data['target_chat']:
            await event.reply("Please set both source and target chats first using /setsource and /settarget.")
        else:
            await event.reply(f"Starting to forward videos from {user_data['source_chat_link']} to {user_data['target_chat']}...")
            await forward_videos_from_source(event.client, user_data['source_chat_link'], user_data['target_chat'], phone_number=phone_number)
        return

    if message_text == '/skip':
        user_data['skip_wait'] = True
        await event.reply("Skipping current flood wait and resuming operations.")
        return


async def forward_videos_from_source(client, source_chat_link, target_chat, boost=False, phone_number=None):
    if not source_chat_link:
        logger.warning("No source chat set. Waiting for input...")
        return

    logger.info(f"Starting to forward videos from {source_chat_link} to {target_chat} for {phone_number}...")

    forwarded_count = 0  # Counter for videos forwarded

    try:
        logger.info(f"Fetching video file IDs from the target channel ({target_chat})...")
        target_videos = set()
        async for message in client.iter_messages(target_chat, filter=InputMessagesFilterVideo):
            if message.video:
                file_id = message.video.id
                if file_id:
                    target_videos.add(file_id)

        logger.info(f"Found {len(target_videos)} video file IDs in the target channel.")

        async for message in client.iter_messages(source_chat_link, filter=InputMessagesFilterVideo, reverse=True):
            if message.video:
                file_id = message.video.id
                if not file_id:
                    file_id = message.document.id if message.document else None

                if file_id and (file_id in forwarded_video_file_ids or file_id in target_videos):
                    logger.info(f"Video {file_id} already exists in the target channel or has been forwarded. Skipping...")
                    continue

                try:
                    await client.send_file(target_chat, message.video)
                    logger.info(f"Forwarded video: {file_id}")
                    forwarded_video_file_ids.add(file_id)
                    target_videos.add(file_id)
                    forwarded_count += 1


                    if forwarded_count >= 50:
                        logger.info(f"Forwarded 50 videos. Pausing for 3600 seconds...")
                        forwarded_count -= 50
                        await asyncio.sleep(3600)

                except errors.FloodWaitError as e:
                    await handle_flood_wait_error(e, client, phone_number)
                except Exception as e:
                    logger.error(f"Error while forwarding video: {e}")

                if not boost:
                    await asyncio.sleep(0.5)
    except Exception as e:
        logger.error(f"Unexpected error: {e}")

    logger.info("Finished forwarding videos.")


async def handle_flood_wait_error(e, client, phone_number):
    wait_time = e.seconds
    logger.warning(f"Flood wait error for {phone_number}: Pausing for {wait_time} seconds...")

    for i in range(wait_time):
        if users_data[phone_number]['skip_wait']:
            users_data[phone_number]['skip_wait'] = False
            break
        await asyncio.sleep(1)


async def start_clients():
    clients = {}
    for api_details in api_credentials:
        phone_number = api_details['phone_number']
        client = TelegramClient(f"forward_user_session_{phone_number}", api_details['api_id'], api_details['api_hash'])

        @client.on(events.NewMessage)
        async def user_message_handler(event, phone_number=phone_number):
            await handle_user_message(event, phone_number)

        await client.start(phone=phone_number)
        clients[phone_number] = client

    await asyncio.gather(*[client.run_until_disconnected() for client in clients.values()])


if __name__ == "__main__":
    import atexit
    atexit.register(save_forwarded_video_file_ids)

    asyncio.run(start_clients())
