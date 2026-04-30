from openai import OpenAI
import os
import base64
from dotenv import load_dotenv
load_dotenv()

client = OpenAI(
    api_key=os.getenv("QWEN_API_KEY"),
    base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
)

image_path = "bps_image.jpg"
with open(image_path, "rb") as image_file:
    image_base64 = base64.b64encode(image_file.read()).decode("utf-8")
image_url = f"data:image/jpeg;base64,{image_base64}"

completion = client.chat.completions.create(
    model="qwen3-vl-plus",
    messages=[
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {
                        "url": image_url
                    },
                },
                {"type": "text", "text": "extract information in this image into a structured markdown format"},
            ],
        },
    ],
)
print(completion.choices[0].message.content)
