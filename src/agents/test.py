from dotenv import load_dotenv
import os
from openai import OpenAI

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

response = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{"role": "user", "content": "Say hello if the API key works!"}]
)

# correct: use .content on the message object
print("✅ API KEY WORKING")
print("Response:", response.choices[0].message.content)
