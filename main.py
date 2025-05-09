from google import genai
from dotenv import load_dotenv
import os

load_dotenv()

api_key = os.getenv("API_KEY")
client = genai.Client(api_key=api_key)



response = client.models.generate_content(
    model="gemini-2.0-flash", contents=["Listen to this podcast 'https://www.twitch.tv/mande', and look for the keyword '1hp'. Find all occurences of the word and give me all the timestamps and sentences used.",]
)

print(response.text)