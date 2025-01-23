# Telegram Bot for Google Calendar Task Management

This is a Telegram bot that helps you manage your Google Calendar events using natural language processing through LangChain and OpenAI.

## Features

- Create calendar events using natural language
- Automatically detects event details (time, date, person, etc.)
- Integrates with Google Calendar
- Uses LangChain for command processing

## Example Usage

Send a message to the bot like:
```
Set a meeting with Mikhail today at 17:00
```

The bot will:
1. Parse your message using LangChain and OpenRouter API
2. Extract relevant event details
3. Create the event in your Google Calendar
4. Send you a link to view the event

## Setup Instructions

1. Clone this repository
2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Set up your environment variables:
   - Copy `.env.example` to `.env`
   - Add your Telegram Bot Token (get it from [@BotFather](https://t.me/botfather))
   - Add your OpenAI API key

4. Set up Google Calendar API:
   - Go to [Google Cloud Console](https://console.cloud.google.com)
   - Create a new project
   - Enable Google Calendar API
   - Create OAuth 2.0 credentials
   - Download the credentials and save as `credentials.json` in the project root

5. Run the bot:
```bash
python bot.py
```

## Requirements

- Python 3.7+
- A Telegram account
- Google account with Calendar access
- OpenAI API key
- Google Cloud project with Calendar API enabled

## Technical Details

The bot uses:
- `python-telegram-bot` for Telegram integration
- `langchain` for natural language processing
- `google-api-python-client` for Google Calendar API
- OpenAI's GPT model for understanding user commands
