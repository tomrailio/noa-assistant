
#
# claude_vision.py
#
# Vision tool implementation based on Anthropic.
#

import base64
from typing import Dict, Optional

import anthropic
from pydantic import BaseModel

from .vision import Vision, VisionOutput
from .utils import detect_media_type
from models import TokenUsage, accumulate_token_usage


SYSTEM_MESSAGE = """
You are Noa, a smart personal AI assistant inside the user's AR smart glasses that answers all user
queries and questions. You have access to a photo from the smart glasses camera of what the user was
seeing at the time they spoke but you NEVER mention the photo or image and instead respond as if you
are actually seeing.

The camera is unfortunately VERY low quality but the user is counting on you to interpret the
blurry, pixelated images. NEVER comment on image quality. Do your best with images.

ALWAYS respond with a JSON object with these fields:

response: (String) Respond to user as best you can. Be precise, get to the point, and speak as though you actually see the image. One or two sentences.
web_query: (String) If a web search for up-to-date, location-based, or product info would be more helpful, generate the query here. But if response was thorough enough, leave blank.
"""

class ModelOutput(BaseModel):
    response: str
    web_query: Optional[str] = None
    reverse_image_search: Optional[bool] = None


class ClaudeVision(Vision):
    def __init__(self, client: anthropic.AsyncAnthropic, model: str="claude-3-haiku-20240307"):
        self._client = client
        self._model = model
    
    async def query_image(self, query: str, extra_context: str, image_bytes: bytes | None, token_usage_by_model: Dict[str, TokenUsage]) -> VisionOutput | None:
        image_base64 = base64.b64encode(image_bytes).decode("utf-8") if image_bytes is not None else ""

        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": detect_media_type(image_bytes=image_bytes),
                            "data": image_base64
                        }
                    },
                    {
                        "type": "text",
                        "text": query
                    }
                ]
            },
            {
                # Prefill a leading '{' to force JSON output as per Anthropic's recommendations
                "role": "assistant",
                "content": [
                    {
                        "type": "text",
                        "text": "{"
                    }
                ]
            }   
        ]

        response = await self._client.messages.create(
            model=self._model,
            system=SYSTEM_MESSAGE + extra_context,
            messages=messages,
            max_tokens=4096,
            temperature=0.0,
        )

        accumulate_token_usage(
            token_usage_by_model=token_usage_by_model,
            model=self._model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            total_tokens=response.usage.input_tokens + response.usage.output_tokens
        )
  
        # Convert to VisionResponse and return
        print(f"VISION:{response.content[0].text}")
        output = self._parse_response(content=response.content[0].text)
        if output is None:
            return None
        web_query = output.web_query if output.web_query is not None else ""
        reverse_image_search = output.reverse_image_search is not None and output.reverse_image_search == True
        if len(web_query) == 0 and reverse_image_search:
            # If no web query output but reverse image search asked for, just use user query
            # directly. This is sub-optimal and it would be better to figure out a way to ensure
            # web_query is generated when reverse_image_search is true.
            web_query = query
        return VisionOutput(response=output.response, web_query=web_query, reverse_image_search=reverse_image_search)
    
    @staticmethod
    def _parse_response(content: str) -> ModelOutput | None:
        # Put the leading '{' back
        json_string = "{" + content
        try:
            return ModelOutput.model_validate_json(json_data=json_string)
        except:
            pass
        return None

Vision.register(ClaudeVision)