
import gspread
import os
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google.auth.exceptions import RefreshError
import datetime

# Google Sheets ID and URL from TOOLS.md
SPREADSHEET_ID = 'SHOWCASE_TIKTOK_IDEAS_SHEET_ID'
SHEET_URL = 'https://docs.google.com/spreadsheets/d/SHOWCASE_TIKTOK_IDEAS_SHEET_ID'

# Path to token file
TOKEN_PATH = os.path.expanduser('~/.openclaw/credentials/google/brand75-brain-token.json')

product_briefs = [
    {
        "Idea": "AI Translation Devices",
        "Category": "AI Product",
        "Tags": "translation, travel, communication",
        "Source": "TikTok Shop",
        "Relevant for": "Dad's Gadget Corner"
    },
    {
        "Idea": "AI-Powered Productivity Mice",
        "Category": "AI Product",
        "Tags": "productivity, voice-to-text, translation, LLM",
        "Source": "TikTok Shop",
        "Relevant for": "Dad's Gadget Corner"
    },
    {
        "Idea": "Rabbit R1 AI Voice-Activated Gadget",
        "Category": "AI Product",
        "Tags": "voice AI, AI chat, productivity, content creation",
        "Source": "Amazon",
        "Relevant for": "Dad's Gadget Corner, Personal TikTok"
    },
    {
        "Idea": "Ray-Ban Meta Gen 2 Glasses",
        "Category": "AI Product",
        "Tags": "wearable AI, smart glasses, AR, live translation",
        "Source": "Amazon",
        "Relevant for": "Dad's Gadget Corner, Personal TikTok"
    },
    {
        "Idea": "Plaud NotePin/Plaud Note Card",
        "Category": "AI Product",
        "Tags": "AI assistant, transcription, meeting summary, productivity",
        "Source": "Amazon",
        "Relevant for": "Dad's Gadget Corner, Personal TikTok"
    },
    {
        "Idea": "OSO AI Earbuds",
        "Category": "AI Product",
        "Tags": "audio AI, transcription, meeting summary, productivity",
        "Source": "Amazon",
        "Relevant for": "Dad's Gadget Corner, Personal TikTok"
    },
    {
        "Idea": "Rocket AI Glasses / Rokid AI glasses",
        "Category": "AI Product",
        "Tags": "wearable AI, smart glasses, AR, real-time translation",
        "Source": "Amazon",
        "Relevant for": "Dad's Gadget Corner, Personal TikTok"
    },
    {
        "Idea": "Momax OneSense Smart Ring",
        "Category": "AI Product",
        "Tags": "wearable AI, health tracking, wellness, sleep analysis",
        "Source": "Amazon",
        "Relevant for": "Dad's Gadget Corner"
    },
    {
        "Idea": "Aibi Pocket Pet",
        "Category": "AI Product",
        "Tags": "novelty AI, wearable robot, ChatGPT",
        "Source": "Amazon",
        "Relevant for": "Dad's Gadget Corner"
    },
    {
        "Idea": "Insta360 Flow 2",
        "Category": "Tech Product",
        "Tags": "AI gimbal, video creation, stabilization",
        "Source": "Amazon",
        "Relevant for": "Personal TikTok"
    },
    {
        "Idea": "SuperPowers AI",
        "Category": "AI Software",
        "Tags": "AI agents, visual agents, phone, wearables",
        "Source": "ProductHunt",
        "Relevant for": "Personal TikTok"
    },
    {
        "Idea": "happycapy",
        "Category": "AI Software",
        "Tags": "AI agents, agent-native computer",
        "Source": "ProductHunt",
        "Relevant for": "Personal TikTok"
    },
    {
        "Idea": "PenguinBot AI",
        "Category": "AI Software",
        "Tags": "AI employee, autonomous tasks, automation",
        "Source": "ProductHunt",
        "Relevant for": "Personal TikTok"
    },
    {
        "Idea": "Anything API (by Notte)",
        "Category": "AI Software",
        "Tags": "AI agent, browser automation, API generation",
        "Source": "ProductHunt",
        "Relevant for": "Personal TikTok"
    },
    {
        "Idea": "Codex app for Windows",
        "Category": "AI Software",
        "Tags": "AI coding, development tools, Windows",
        "Source": "ProductHunt",
        "Relevant for": "Personal TikTok"
    },
    {
        "Idea": "TestSprite 1.0",
        "Category": "AI Software",
        "Tags": "AI agent, software testing, automation",
        "Source": "ProductHunt",
        "Relevant for": "Personal TikTok"
    },
    {
        "Idea": "Sagehood",
        "Category": "AI Software",
        "Tags": "AI agents, stock market analysis, finance",
        "Source": "ProductHunt",
        "Relevant for": "Personal TikTok"
    },
    {
        "Idea": "Wegic",
        "Category": "AI Software",
        "Tags": "AI website team, web development, automation",
        "Source": "ProductHunt",
        "Relevant for": "Personal TikTok"
    },
    # Newly researched products from TikTok Shop, Amazon, and ProductHunt
    {
        "Idea": "Ray-Ban Meta Gen 2 Glasses (New)",
        "Category": "AI Product",
        "Tags": "wearable AI, smart glasses, AR, real-time translation, camera",
        "Source": "TikTok Shop, Amazon",
        "Relevant for": "Dad's Gadget Corner, Personal TikTok"
    },
    {
        "Idea": "Portable AI Translator Devices (New)",
        "Category": "AI Product",
        "Tags": "translation, travel, communication, real-time",
        "Source": "TikTok Shop, Amazon",
        "Relevant for": "Dad's Gadget Corner"
    },
    {
        "Idea": "AI-Powered Productivity Mouse (New)",
        "Category": "AI Product",
        "Tags": "productivity, voice-to-text, translation, LLM, ChatGPT shortcuts",
        "Source": "TikTok Shop, Amazon",
        "Relevant for": "Dad's Gadget Corner"
    },
    {
        "Idea": "Plaud NotePin (New)",
        "Category": "AI Product",
        "Tags": "AI assistant, transcription, meeting summary, productivity, wearable",
        "Source": "Amazon",
        "Relevant for": "Dad's Gadget Corner, Personal TikTok"
    },
    {
        "Idea": "Rabbit R1 AI Voice-Activated Gadget (New)",
        "Category": "AI Product",
        "Tags": "voice AI, AI chat, productivity, content creation, portable",
        "Source": "Amazon",
        "Relevant for": "Dad's Gadget Corner, Personal TikTok"
    },
    {
        "Idea": "RingConn Gen 2 Air Smart Ring (New)",
        "Category": "AI Product",
        "Tags": "wearable AI, health tracking, wellness, sleep analysis, smart ring",
        "Source": "Amazon",
        "Relevant for": "Dad's Gadget Corner"
    },
    {
        "Idea": "Insta360 Flow 2 (AI gimbal) (New)",
        "Category": "Tech Product",
        "Tags": "AI gimbal, video creation, stabilization, smartphone accessory",
        "Source": "Amazon",
        "Relevant for": "Dad's Gadget Corner"
    },
    {
        "Idea": "Superpowers AI (New)",
        "Category": "AI Software",
        "Tags": "AI agents, visual agents, phone, wearables",
        "Source": "ProductHunt",
        "Relevant for": "Personal TikTok"
    },
    {
        "Idea": "Aident AI Beta 2 (New)",
        "Category": "AI Software",
        "Tags": "AI agents, automation, integrations, editor",
        "Source": "ProductHunt",
        "Relevant for": "Personal TikTok"
    },
    {
        "Idea": "Kimi Claw (New)",
        "Category": "AI Software",
        "Tags": "AI agents, automation, persistent tasks, agent swarm",
        "Source": "ProductHunt",
        "Relevant for": "Personal TikTok"
    },
    {
        "Idea": "Straion (AI Coding Standards) (New)",
        "Category": "AI Software",
        "Tags": "AI coding, coding standards, Claude Code, GitHub Copilot",
        "Source": "ProductHunt",
        "Relevant for": "Personal TikTok"
    },
    {
        "Idea": "Tidy (Personal AI Agent) (New)",
        "Category": "AI Software",
        "Tags": "AI agent, personal assistant, persistent memory, web/desktop app automation",
        "Source": "ProductHunt",
        "Relevant for": "Personal TikTok"
    },
    {
        "Idea": "Clawi.ai (OpenClaw Cloud) (New)",
        "Category": "AI Software",
        "Tags": "OpenClaw, AI agents, cloud platform, private assistants",
        "Source": "ProductHunt",
        "Relevant for": "Personal TikTok"
    },
    {
        "Idea": "KiloClaw (Hosted OpenClaw) (New)",
        "Category": "AI Infrastructure",
        "Tags": "OpenClaw, hosting, infrastructure, agent framework",
        "Source": "ProductHunt",
        "Relevant for": "Personal TikTok"
    }
]

def add_product_briefs():
    try:
        creds = None
        if os.path.exists(TOKEN_PATH):
            creds = Credentials.from_authorized_user_file(TOKEN_PATH)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except RefreshError as e:
                    print(f"Error: Token refresh failed: {e}. You may need to re-authenticate.")
                    raise Exception("Google Sheets authentication failed.")
            else:
                print("Error: No valid token found or token is invalid/expired without refresh token. Please ensure OAuth flow has been completed.")
                raise Exception("Google Sheets authentication failed.")

        gc = gspread.authorize(creds)
        spreadsheet = gc.open_by_url(SHEET_URL)
        worksheet = spreadsheet.sheet1
        
        current_date = datetime.date.today().strftime("%Y-%m-%d")
        
        for product in product_briefs:
            row = [
                current_date,
                product["Idea"],
                product["Category"],
                product["Tags"],
                product["Source"],
                "", # Doc Link (leaving blank for now)
                "New"
            ]
            worksheet.append_row(row)
            print(f"Added: {product["Idea"]}")
            
        print("All qualifying product briefs added to the TikTok Ideas Backlog Sheet.")
        
    except gspread.exceptions.SpreadsheetNotFound:
        print(f"Error: Spreadsheet with URL {SHEET_URL} not found.")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

if __name__ == "__main__":
    add_product_briefs()
