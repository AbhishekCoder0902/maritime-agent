# pyrefly: ignore [missing-import]
import feedparser
import json
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta
import urllib.parse
from google import genai
from google.genai import types
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configuration
FEEDS = [
    "https://gcaptain.com/feed/",
    "https://splash247.com/feed/",
    "https://news.google.com/rss/search?q=" + urllib.parse.quote('("ship" OR "maritime" OR "vessel" OR "port") when:7d')
]

def fetch_recent_news():
    """Fetches news from RSS feeds published in the last 7 days."""
    print("Fetching news from RSS feeds...")
    seven_days_ago = datetime.now() - timedelta(days=7)
    articles = []

    for feed_url in FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries:
                # Handle different date formats in RSS
                pub_date = None
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    pub_date = datetime(*entry.published_parsed[:6])
                elif hasattr(entry, 'updated_parsed') and entry.updated_parsed:
                    pub_date = datetime(*entry.updated_parsed[:6])
                
                if pub_date and pub_date > seven_days_ago:
                    articles.append({
                        "title": entry.title,
                        "link": entry.link,
                        "summary": entry.summary if hasattr(entry, 'summary') else "",
                        "published": pub_date.strftime("%Y-%m-%d %H:%M:%S")
                    })
        except Exception as e:
            print(f"Failed to parse {feed_url}: {e}")

    # Remove duplicates based on title
    unique_articles = {article['title']: article for article in articles}.values()
    print(f"Found {len(unique_articles)} recent articles.")
    return list(unique_articles)

def analyze_news_with_gemini(articles):
    """Uses Gemini API to extract the required intelligence brief."""
    print("Analyzing news with Gemini...")
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY environment variable is missing.")

    client = genai.Client(api_key=api_key)
    
    # We pass only a subset of the data if it's too large, but Gemini 1.5/2.0 context is huge.
    # Let's format the articles as a string
    articles_text = ""
    for i, a in enumerate(articles[:100]): # Limit to top 100 to save some tokens
        articles_text += f"[{i+1}] Title: {a['title']}\nLink: {a['link']}\nSummary: {a['summary'][:200]}...\nDate: {a['published']}\n\n"

    prompt = f"""
    You are an expert maritime intelligence analyst. Review the following news articles from the past 7 days.
    
    Extract and structure the following information EXACTLY as requested:
    
    1. Top 5 maritime news stories: Select the 5 most important stories relevant to shipowners, port operations, and marine inspections. For each, provide a 2-line summary and the source link.
    2. Major incident: Identify one major incident (collision, grounding, detention, sanctions action) involving a vessel over 10,000 GT in the past 7 days. (If GT is not specified, infer if it's a large commercial vessel. If absolutely no major incident is found, state that).
    3. Opportunity signal: Identify one new port project, regulation change, or company announcement that could translate into a business opening for a maritime consulting/solutions firm (NavGuide Solutions), and provide your reasoning for why it matters.

    Respond in valid JSON format ONLY with the following schema:
    {{
        "top_5_news": [
            {{"headline": "...", "summary": "...", "link": "..."}}
        ],
        "major_incident": {{
            "incident": "...",
            "details": "..."
        }},
        "opportunity_signal": {{
            "signal": "...",
            "reasoning": "..."
        }}
    }}
    
    News Articles:
    {articles_text}
    """
    
    # Retry logic for Gemini API (handles 503 High Demand errors)
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.2,
                ),
            )
            break
        except Exception as e:
            if "503" in str(e) and attempt < max_retries - 1:
                import time
                wait_time = (attempt + 1) * 5
                print(f"Gemini API high demand (503). Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
            else:
                raise
    
    try:
        return json.loads(response.text)
    except json.JSONDecodeError:
        print("Failed to decode JSON from Gemini response.")
        print(response.text)
        raise

def format_email_html(brief_data):
    """Formats the JSON data into a clean HTML email."""
    html = f"""
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
            h2 {{ color: #003366; border-bottom: 2px solid #003366; padding-bottom: 5px; }}
            h3 {{ color: #004080; }}
            .news-item {{ margin-bottom: 20px; }}
            .news-item h4 {{ margin: 0 0 5px 0; }}
            .news-item p {{ margin: 0 0 5px 0; }}
            .highlight {{ background-color: #f0f7ff; padding: 15px; border-left: 4px solid #00509e; margin-bottom: 20px; }}
            a {{ color: #0066cc; text-decoration: none; }}
            a:hover {{ text-decoration: underline; }}
        </style>
    </head>
    <body>
        <h2>Weekly Maritime Intelligence Brief</h2>
        <p><em>Generated on {datetime.now().strftime("%B %d, %Y at %H:%M IST")}</em></p>

        <h3>Top 5 Maritime News Stories</h3>
    """
    
    for i, item in enumerate(brief_data.get("top_5_news", [])):
        html += f"""
        <div class="news-item">
            <h4>{i+1}. {item['headline']}</h4>
            <p>{item['summary']}</p>
            <p><a href="{item['link']}">Source Link</a></p>
        </div>
        """
        
    html += """
        <h3>Major Incident (>10,000 GT)</h3>
        <div class="highlight">
    """
    incident = brief_data.get("major_incident", {})
    html += f"""
            <h4>{incident.get('incident', 'No major incidents reported matching criteria.')}</h4>
            <p>{incident.get('details', '')}</p>
        </div>
        
        <h3>Opportunity Signal</h3>
        <div class="highlight">
    """
    opportunity = brief_data.get("opportunity_signal", {})
    html += f"""
            <h4>{opportunity.get('signal', 'No clear opportunity signals detected.')}</h4>
            <p><strong>Why it matters for NavGuide Solutions:</strong> {opportunity.get('reasoning', '')}</p>
        </div>
        
        <p><br><em>This brief was automatically generated by the NavGuide AI Executor.</em></p>
    </body>
    </html>
    """
    return html

def send_email(html_content):
    """Sends the HTML email via SMTP."""
    sender_email = os.environ.get("SMTP_EMAIL")
    sender_password = os.environ.get("SMTP_PASSWORD")
    recipient_email = "captain@navguidesolutions.com"
    
    if not sender_email or not sender_password:
        print("SMTP credentials not set. Skipping email delivery.")
        # We will save it to a file instead so we can see the output locally
        with open("local_brief_output.html", "w", encoding="utf-8") as f:
            f.write(html_content)
        print("Brief saved to local_brief_output.html")
        return

    msg = MIMEMultipart('alternative')
    msg['Subject'] = "Weekly Maritime Intelligence Brief"
    msg['From'] = sender_email
    msg['To'] = recipient_email

    part = MIMEText(html_content, 'html')
    msg.attach(part)

    try:
        # Using Gmail SMTP as default
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(sender_email, sender_password)
        server.sendmail(sender_email, recipient_email, msg.as_string())
        server.quit()
        print("Email sent successfully!")
    except Exception as e:
        print(f"Failed to send email: {e}")

def main():
    try:
        articles = fetch_recent_news()
        if not articles:
            print("No articles found in the past 7 days.")
            return
            
        brief_data = analyze_news_with_gemini(articles)
        html_report = format_email_html(brief_data)
        send_email(html_report)
        print("Weekly brief pipeline completed.")
        
    except Exception as e:
        print(f"Pipeline failed: {e}")

if __name__ == "__main__":
    main()
