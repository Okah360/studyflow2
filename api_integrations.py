"""
StudyFlow API Integrations Module
Handles Google OAuth, Calendar, Email, Weather, Discord, and OpenAI integrations
"""

import os
import json
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

# ============================================================================
# GOOGLE CALENDAR INTEGRATION
# ============================================================================

def sync_task_to_google_calendar(task, user_token):
    """Sync a StudyFlow task to Google Calendar"""
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import Flow
        from googleapiclient.discovery import build
        
        if not user_token:
            return {"error": "User not authenticated with Google"}
        
        creds = Credentials(user_token)
        service = build('calendar', 'v3', credentials=creds)
        
        event = {
            'summary': task.get('name'),
            'description': task.get('notes', ''),
            'start': {'date': task.get('due_date')} if task.get('due_date') else None,
            'end': {'date': task.get('due_date')} if task.get('due_date') else None,
        }
        
        if event['start']:
            result = service.events().insert(calendarId='primary', body=event).execute()
            return {"success": True, "event_id": result.get('id')}
        
        return {"error": "Task has no due date"}
    except Exception as e:
        return {"error": str(e)}


# ============================================================================
# EMAIL NOTIFICATIONS
# ============================================================================

def send_task_reminder(user_email, task):
    """Send email reminder for a task"""
    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail
        
        sg = SendGridAPIClient(os.getenv('SENDGRID_API_KEY'))
        
        message = Mail(
            from_email=os.getenv('SENDGRID_FROM_EMAIL'),
            to_emails=user_email,
            subject=f"Task Reminder: {task.get('name')}",
            html_content=f"""
            <h2>Task Reminder</h2>
            <p><strong>{task.get('name')}</strong></p>
            <p>Priority: {task.get('priority', 'medium').upper()}</p>
            <p>Due: {task.get('due_date', 'No date set')}</p>
            <p>Duration: {task.get('duration', 'Not specified')}</p>
            {f"<p>Notes: {task.get('notes')}</p>" if task.get('notes') else ""}
            <p><a href="http://127.0.0.1:5000">View on StudyFlow</a></p>
            """
        )
        
        response = sg.send(message)
        return {"success": True, "status_code": response.status_code}
    except Exception as e:
        return {"error": str(e)}


# ============================================================================
# WEATHER API
# ============================================================================

def get_weather_for_date(date_str, latitude=None, longitude=None):
    """Get weather forecast for a specific date"""
    try:
        lat = latitude or os.getenv('DEFAULT_USER_LATITUDE', '40.7128')
        lon = longitude or os.getenv('DEFAULT_USER_LONGITUDE', '-74.0060')
        
        url = os.getenv('WEATHER_API_URL')
        params = {
            'lat': lat,
            'lon': lon,
            'appid': os.getenv('WEATHER_API_KEY'),
            'units': 'metric'
        }
        
        response = requests.get(url, params=params, timeout=5)
        if response.status_code == 200:
            data = response.json()
            return {
                "success": True,
                "temp": data.get('main', {}).get('temp'),
                "description": data.get('weather', [{}])[0].get('description'),
                "icon": data.get('weather', [{}])[0].get('icon'),
                "humidity": data.get('main', {}).get('humidity'),
                "wind_speed": data.get('wind', {}).get('speed')
            }
        return {"error": "Could not fetch weather"}
    except Exception as e:
        return {"error": str(e)}


# ============================================================================
# DISCORD WEBHOOK
# ============================================================================

def send_discord_notification(task, action='created'):
    """Send task notification to Discord"""
    try:
        from discord_webhook import DiscordWebhook, DiscordEmbed
        
        webhook_url = os.getenv('DISCORD_WEBHOOK_URL')
        if not webhook_url:
            return {"error": "Discord webhook not configured"}
        
        webhook = DiscordWebhook(url=webhook_url)
        
        embed = DiscordEmbed(
            title=f"Task {action.capitalize()}: {task.get('name')}",
            description=task.get('notes', 'No notes'),
            color="3498db"
        )
        embed.add_embed_field(name="Priority", value=task.get('priority', 'medium').upper(), inline=True)
        embed.add_embed_field(name="Due Date", value=task.get('due_date', 'No date'), inline=True)
        embed.add_embed_field(name="Duration", value=task.get('duration', 'Not specified'), inline=True)
        
        webhook.add_embed(embed)
        response = webhook.execute()
        return {"success": True}
    except Exception as e:
        return {"error": str(e)}


# ============================================================================
# OPENAI INTEGRATION
# ============================================================================

def get_ai_task_suggestions(user_tasks, query):
    """Get AI-powered task suggestions using OpenAI"""
    try:
        import openai
        
        openai.api_key = os.getenv('OPENAI_API_KEY')
        
        task_list = "\n".join([f"- {t.get('name')} (Priority: {t.get('priority')})" for t in user_tasks])
        
        prompt = f"""
        Based on the user's current tasks:
        {task_list}
        
        User query: {query}
        
        Provide helpful study suggestions or task recommendations in 2-3 sentences.
        """
        
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=150,
            temperature=0.7
        )
        
        suggestion = response.choices[0].message.content
        return {"success": True, "suggestion": suggestion}
    except Exception as e:
        return {"error": str(e)}


def generate_task_from_description(description):
    """Use OpenAI to parse a task description and extract details"""
    try:
        import openai
        
        openai.api_key = os.getenv('OPENAI_API_KEY')
        
        prompt = f"""
        Parse this task description and extract the following in JSON format:
        - name (task name)
        - priority (low/medium/high)
        - estimated_duration (e.g. "30 minutes", "2 hours")
        - notes (any additional details)
        
        Description: {description}
        
        Return ONLY valid JSON, no other text.
        """
        
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
            temperature=0.7
        )
        
        task_json = response.choices[0].message.content
        task_data = json.loads(task_json)
        return {"success": True, "task": task_data}
    except Exception as e:
        return {"error": str(e)}


# ============================================================================
# HEALTH CHECK
# ============================================================================

def check_api_status():
    """Check which APIs are properly configured"""
    status = {
        "google_oauth": bool(os.getenv('GOOGLE_CLIENT_ID')),
        "sendgrid_email": bool(os.getenv('SENDGRID_API_KEY')),
        "weather_api": bool(os.getenv('WEATHER_API_KEY')),
        "discord_webhook": bool(os.getenv('DISCORD_WEBHOOK_URL')),
        "openai": bool(os.getenv('OPENAI_API_KEY')),
    }
    return status
