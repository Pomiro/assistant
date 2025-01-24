import os
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from langchain.prompts import ChatPromptTemplate
from langchain.output_parsers import ResponseSchema, StructuredOutputParser
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
import pickle
from openai import OpenAI
import logging

# Logging template
logging.basicConfig(filename="bot.log",encoding="utf-8", level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Load environment variables
load_dotenv()

# Google Calendar API setup
SCOPES = ['https://www.googleapis.com/auth/calendar']
model = 'qwen/qwen-2-7b-instruct:free'

def get_google_calendar_service():
    """Set up and return Google Calendar service."""
    creds = None
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        
        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)

    return build('calendar', 'v3', credentials=creds)

# LangChain setup for request classification
request_type_schema = [
    ResponseSchema(name="type", description="Type of request: 'add_event' or 'show_today'"),
    ResponseSchema(name="original_text", description="Original text if type is add_event")
]

request_classifier = StructuredOutputParser.from_response_schemas(request_type_schema)

classifier_prompt = ChatPromptTemplate.from_template("""
Classify the following request into one of these types:
1. add_event - when user wants to add an event to calendar
2. show_today - when user wants to see today's meta-events

Text: {text}

{format_instructions}
""")

# LangChain setup for event parsing
event_schemas = [
    ResponseSchema(name="event_type", description="Type of calendar event (meeting, task, etc.)"),
    ResponseSchema(name="title", description="Title or description of the event"),
    ResponseSchema(name="date", description="Date of the event"),
    ResponseSchema(name="time", description="Time of the event"),
    ResponseSchema(name="person", description="Person involved in the event (if any)"),
    ResponseSchema(name="event_duration", description="Duration of event", type='float')
]

event_parser = StructuredOutputParser.from_response_schemas(event_schemas)

event_prompt = ChatPromptTemplate.from_template("""
Extract calendar event information from the following text. If any information is missing, leave it blank.

Text: {text}

{format_instructions}
""")

def normalize_datetime(date_str: str, time_str: str) -> datetime:
    """Normalize date and time strings to datetime object."""
    # Get current time in Asia/Yekaterinburg timezone
    tz = timezone(timedelta(hours=5))  # UTC+5 for Yekaterinburg
    now = datetime.now(tz).replace(tzinfo=None)
    
    # Handle relative dates
    date_lower = date_str.lower()
    if date_lower == 'today' or '' or 'сегодня':
        date = now.date()
    elif date_lower == 'tomorrow' or 'завтра':
        date = (now + timedelta(days=1)).date()
    else:
        try:
            # Try parsing the date in various formats
            for fmt in ['%Y-%m-%d', '%d-%m-%Y', '%d.%m.%Y', '%d/%m/%Y']:
                try:
                    date = datetime.strptime(date_str, fmt).date()
                    break
                except ValueError:
                    continue
            else:
                raise ValueError("Unsupported date format")
        except ValueError:
            raise ValueError("Please provide date in YYYY-MM-DD format or use 'today'/'tomorrow'")
    
    # Parse time
    try:
        # Try 24-hour format first
        time = datetime.strptime(time_str, '%H:%M').time()
    except ValueError:
        raise ValueError("Please provide time in HH:MM format (24-hour)")
            
    # Combine date and time
    dt = datetime.combine(date, time)
    
    # Ensure event is not in the past
    if dt < now:
        if date_lower == 'today':
            raise ValueError("Cannot create events in the past. Please specify a future time.")
        
    return dt

async def create_calendar_event(event_details):
    """Create a calendar event using Google Calendar API."""
    try:
        service = get_google_calendar_service()
        
        if not event_details.get('time'):
            raise ValueError("Time are required")
        
        try:
            start_time = normalize_datetime(event_details['date'], event_details['time'])
        except ValueError as e:
            raise ValueError(f"Date/time error: {str(e)}")
        
        # Set event duration
        duration = 1
        if event_details.get('event_duration'):
            event_duration = event_details['event_duration']
            try:
                duration = float(event_duration)
            except:
                duration = 1
        
        event = {
            'summary': event_details['title'],
            'start': {
                'dateTime': start_time.isoformat(),
                'timeZone': 'Asia/Yekaterinburg',
            },
            'end': {
                'dateTime': (start_time + timedelta(hours=duration)).isoformat(),
                'timeZone': 'Asia/Yekaterinburg',
            },
        }
        
        if event_details.get('person'):
            event['description'] = f"Meeting with {event_details['person']}"
        logging.info(f'Final event: {event}')
        event = service.events().insert(calendarId='primary', body=event).execute()
        return event.get('htmlLink')
    except Exception as e:
        raise ValueError(f"Failed to create calendar event: {str(e)}")

async def get_today_events(service):
    """Get today's events from calendar."""
    tz = timezone(timedelta(hours=5))  # UTC+5 for Yekaterinburg
    now = datetime.now(tz)
    
    today_start = datetime.combine(now.date(), datetime.min.time()).astimezone(tz)
    today_end = datetime.combine(now.date(), datetime.max.time()).astimezone(tz)
    
    events_result = service.events().list(
        calendarId='primary',
        timeMin=today_start.isoformat(),
        timeMax=today_end.isoformat(),
        singleEvents=True,
        orderBy='startTime'
    ).execute()
    
    return events_result.get('items', [])

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming messages and process requests."""
    try:
        logging.info(f"Received a message: {update.message.text}")

        # OpenAI Client Setup
        client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=os.getenv("OPENROUTER_API_KEY"),
        )

        # First, classify the request
        _classifier_prompt = classifier_prompt.format_messages(
            text=update.message.text,
            format_instructions=request_classifier.get_format_instructions()
        )
        
        classifier_completion = client.chat.completions.create(
            extra_headers={
                "HTTP-Referer": "",
                "X-Title": "",
            },
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": _classifier_prompt[0].content
                }
            ]
        )
        
        request_type = request_classifier.parse(classifier_completion.choices[0].message.content)
        logging.info(f'Request type: {request_type}')

        if request_type['type'] == 'show_today':
            # Handle show today's events request
            service = get_google_calendar_service()
            events = await get_today_events(service)
            
            if not events:
                await update.message.reply_text("No events scheduled for today.")
                return
                
            response = "Today's events:\n\n"
            for event in events:
                start = event['start'].get('dateTime', event['start'].get('date'))
                start_time = datetime.fromisoformat(start).astimezone(timezone(timedelta(hours=5)))
                response += f"• {start_time.strftime('%H:%M')} - {event['summary']}\n"
            
            await update.message.reply_text(response)
            
        elif request_type['type'] == 'add_event':
            # Format the event prompt
            _event_prompt = event_prompt.format_messages(
                text=request_type['original_text'],
                format_instructions=event_parser.get_format_instructions()
            )

            # Get event details
            event_completion = client.chat.completions.create(
                extra_headers={
                    "HTTP-Referer": "",
                    "X-Title": "",
                },
                model=model,
                messages=[
                    {
                        "role": "user",
                        "content": _event_prompt[0].content
                    }
                ]
            )
            
            event_details = event_parser.parse(event_completion.choices[0].message.content)
            logging.info(f'Event details: {event_details}')
            
            # Create calendar event
            event_link = await create_calendar_event(event_details)
            await update.message.reply_text(f"Event created successfully!\nView it here: {event_link}")
        
        else:
            await update.message.reply_text(
                "I'm not sure what you want to do. You can ask me to:\n"
                "1. Add an event (e.g., 'Set a meeting tomorrow at 15:00')\n"
                "2. Show today's events (e.g., 'What's on my schedule today?')"
            )
        
    except Exception as e:
        await update.message.reply_text(
            f"Sorry, I couldn't process that request. Error: {str(e)}"
        )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a message when the command /start is issued."""
    await update.message.reply_text(
        "Hi! I'm your Calendar Bot. You can:\n"
        "1. Create events (e.g., 'Set a meeting with Mikhail today at 17:00')\n"
        "2. View today's events (e.g., 'What's on my schedule today?')"
    )

def main():
    logging.info(f"Start the bot")
    # Create application
    application = Application.builder().token(os.getenv('TELEGRAM_TOKEN')).build()

    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Run the bot
    application.run_polling()

if __name__ == '__main__':
    main()
