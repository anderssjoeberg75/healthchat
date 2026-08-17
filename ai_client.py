"""
Multi-provider AI client for Garmin Chat Desktop.
Supports: xAI (Grok), OpenAI (ChatGPT), Azure OpenAI, Google Gemini, Anthropic (Claude)
"""

from openai import OpenAI, AzureOpenAI
from typing import List, Dict, Optional
import logging
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class AIClient:
    """Unified AI client that supports multiple providers."""
    
    # Provider configurations
    PROVIDERS = {
        'xai': {
            'name': 'xAI (Grok)',
            'base_url': 'https://api.x.ai/v1',
            'models': ['grok-3', 'grok-vision-beta', 'grok-2-vision-1212'],
            'default_model': 'grok-3',
            'supports_streaming': True
        },
        'openai': {
            'name': 'OpenAI (ChatGPT)',
            'base_url': 'https://api.openai.com/v1',
            'models': ['gpt-4o', 'gpt-4o-mini', 'gpt-4-turbo', 'gpt-3.5-turbo'],
            'default_model': 'gpt-4o',
            'supports_streaming': True
        },
        'azure': {
            'name': 'Azure OpenAI',
            'base_url': None,  # Set by user
            'models': [],  # Deployment names set by user
            'default_model': None,
            'supports_streaming': True,
            'requires_deployment': True
        },
        'gemini': {
            'name': 'Google Gemini',
            'base_url': 'https://generativelanguage.googleapis.com/v1beta',
            'models': ['gemini-1.5-flash', 'gemini-1.5-flash-8b', 'gemini-1.5-pro'],
            'default_model': 'gemini-1.5-flash',
            'supports_streaming': True,
            'uses_native_sdk': True,  # Use native Google SDK (google-genai package)
            'note': 'Requires google-genai package (replaces deprecated google-generativeai)'
        },
        'anthropic': {
            'name': 'Anthropic (Claude)',
            'base_url': 'https://api.anthropic.com/v1',
            'models': ['claude-opus-4-6', 'claude-sonnet-4-6', 'claude-haiku-4-5-20251001', 'claude-opus-4-5-20251101', 'claude-sonnet-4-5-20250929', 'claude-3-5-sonnet-20241022', 'claude-3-5-haiku-20241022'],
            'default_model': 'claude-sonnet-4-6',
            'supports_streaming': True,
            'uses_anthropic_sdk': True
        },
        'ollama': {
            'name': 'Ollama (Local)',
            'base_url': 'http://localhost:11434/v1',
            'models': ['llama3.2', 'llama3.1', 'llama3', 'mistral', 'mixtral', 'gemma2', 'phi3', 'qwen2.5', 'deepseek-r1'],
            'default_model': 'llama3.2',
            'supports_streaming': True,
            'local': True,
            'note': 'Requires Ollama running locally (https://ollama.com). No API key needed.'
        }
    }
    
    def __init__(self, provider: str = 'xai', api_key: str = '', model: str = None, **kwargs):
        """
        Initialize AI client with specified provider.
        
        Args:
            provider: One of 'xai', 'openai', 'azure', 'gemini', 'anthropic'
            api_key: API key for the provider
            model: Specific model to use (uses default if not specified)
            **kwargs: Additional provider-specific parameters
                - azure_endpoint: Azure OpenAI endpoint URL
                - azure_deployment: Azure deployment name
                - azure_api_version: Azure API version (default: 2024-02-15-preview)
        """
        self.provider = provider
        self.api_key = api_key
        self.conversation_history: List[Dict[str, str]] = []
        
        if provider not in self.PROVIDERS:
            raise ValueError(f"Unsupported provider: {provider}. Choose from: {list(self.PROVIDERS.keys())}")
        
        provider_config = self.PROVIDERS[provider]
        
        # Set model (use default if not specified)
        if model:
            self.model = model
        else:
            self.model = provider_config['default_model']
        
        # Initialize provider-specific client
        if provider == 'xai':
            self.client = self._init_xai()
        elif provider == 'openai':
            self.client = self._init_openai()
        elif provider == 'azure':
            self.client = self._init_azure(kwargs)
        elif provider == 'gemini':
            self.client = self._init_gemini()
        elif provider == 'anthropic':
            self.client = self._init_anthropic()
        elif provider == 'ollama':
            self.client = self._init_ollama(kwargs)
        
        logger.info(f"Initialized {provider_config['name']} with model: {self.model}")
    
    def _init_xai(self):
        """Initialize xAI (Grok) client."""
        return OpenAI(
            api_key=self.api_key,
            base_url=self.PROVIDERS['xai']['base_url']
        )
    
    def _init_openai(self):
        """Initialize OpenAI (ChatGPT) client."""
        return OpenAI(api_key=self.api_key)
    
    def _init_azure(self, kwargs):
        """Initialize Azure OpenAI client."""
        azure_endpoint = kwargs.get('azure_endpoint')
        if not azure_endpoint:
            raise ValueError("Azure OpenAI requires 'azure_endpoint' parameter")
        
        # For Azure, model is actually the deployment name
        azure_deployment = kwargs.get('azure_deployment', self.model)
        self.azure_deployment = azure_deployment
        
        api_version = kwargs.get('azure_api_version', '2024-02-15-preview')
        
        return AzureOpenAI(
            api_key=self.api_key,
            azure_endpoint=azure_endpoint,
            api_version=api_version
        )
    
    def _init_gemini(self):
        """Initialize Google Gemini client (using new google-genai SDK)."""
        try:
            import google.genai as genai
            # New API uses Client object
            # Try with v1 API version instead of default v1beta
            try:
                # Attempt with v1 first (more stable, has generateContent)
                client = genai.Client(
                    api_key=self.api_key,
                    http_options={'api_version': 'v1'}
                )
                logger.info("Initialized Gemini client with API version v1")
            except:
                # Fallback to default (v1beta)
                client = genai.Client(api_key=self.api_key)
                logger.info("Initialized Gemini client with default API version")
            return client
        except ImportError:
            logger.error("google-genai package not installed. Install with: pip install google-genai")
            raise ImportError("google-genai package is required for Gemini. Install with: pip install google-genai")
    
    def _init_anthropic(self):
        """Initialize Anthropic (Claude) client."""
        try:
            from anthropic import Anthropic
            import httpx
            # Use an explicit httpx client to avoid 'proxies' keyword argument
            # errors caused by version mismatches between anthropic SDK and httpx.
            # Newer Anthropic SDK versions (0.40+) dropped the proxies parameter.
            http_client = httpx.Client()
            return Anthropic(api_key=self.api_key, http_client=http_client)
        except ImportError as e:
            if 'anthropic' in str(e):
                # Fallback to OpenAI-compatible interface if anthropic SDK not installed
                logger.warning("Anthropic SDK not installed, using OpenAI-compatible interface")
                return OpenAI(
                    api_key=self.api_key,
                    base_url=self.PROVIDERS['anthropic']['base_url']
                )
            raise
    
    def _init_ollama(self, kwargs):
        """Initialize Ollama local client using OpenAI-compatible API."""
        base_url = kwargs.get('ollama_base_url', self.PROVIDERS['ollama']['base_url'])
        # Ollama uses OpenAI-compatible API, no real API key needed
        return OpenAI(
            api_key='ollama',  # Ollama ignores the key but OpenAI client requires one
            base_url=base_url
        )
    
    def chat(
        self, 
        user_message: str, 
        garmin_context: Optional[str] = None,
        system_prompt: Optional[str] = None
    ) -> str:
        """
        Send a chat message to the AI provider.
        
        Args:
            user_message: User's question or message
            garmin_context: Formatted Garmin data to provide as context
            system_prompt: Optional system prompt override
            
        Returns:
            AI's response as a string
        """
        # Default system prompt
        if system_prompt is None:
            system_prompt = """You are a helpful fitness and health assistant with access to the user's Garmin Connect data. 
You help users understand their fitness data, track their progress, and provide insights about their health metrics.

AVAILABLE DATA TYPES:
The system can access the following Garmin data:
- Activities (runs, walks, bike rides, workouts, etc.)
- Sleep data (total, deep, light, REM, awake time)
- Steps and distance
- Heart rate (resting, active, zones)
- Body Battery (energy levels throughout the day)
- Stress levels (average, rest, activity, duration by intensity)
- Respiration rate (waking and sleeping)
- Hydration (water intake)
- Nutrition (calories consumed and burned)
- Floors climbed (ascended and descended)
- Intensity minutes (moderate and vigorous activity)
- Blood oxygen / SpO2 (pulse oximetry)
- Heart Rate Variability (HRV)
- VO2 Max and fitness age
- Training status and load
- Body composition

IMPORTANT DATA CONTEXT:
- The activity data shows the user's most recent activities (typically 5-30 depending on the query)
- Activities are ordered by date (newest first)
- When users ask about TIME PERIODS (like "last 30 days", "this month", "last week"), the data will cover that specific date range
- When users ask about ACTIVITY COUNTS (like "last 10 runs"), the data shows that many activities

When users ask about HEALTH METRICS (Body Battery, stress, HRV, etc.):
- Provide the specific numbers and explain what they mean
- Offer context on whether the values are good/normal
- Suggest factors that might influence these metrics
- Connect metrics when relevant (e.g., low Body Battery and high stress often correlate)

When answering questions:
- Be conversational and friendly
- Provide specific numbers and data when available
- Be precise about date ranges - check the actual dates in the activity data
- Offer insights and trends when relevant
- Suggest actionable advice when appropriate
- If you need more data or a different date range, clearly explain what you need
- NEVER apologize for limitations - instead, explain what you CAN do
- When discussing health metrics like Body Battery or stress, provide context and interpretation

The user's Garmin data will be provided in the context below."""
        
        # Build message with context
        if garmin_context:
            full_message = f"{garmin_context}\n\nUser Question: {user_message}"
        else:
            full_message = user_message
        
        # Add to conversation history
        self.conversation_history.append({
            'role': 'user',
            'content': full_message
        })
        
        try:
            # Call appropriate provider
            if self.provider == 'anthropic' and hasattr(self.client, 'messages'):
                # Use native Anthropic SDK
                response = self._call_anthropic(system_prompt)
            elif self.provider == 'gemini':
                # Use native Gemini SDK (new google-genai package)
                response = self._call_gemini(system_prompt, full_message)
            else:
                # Use OpenAI-compatible interface
                response = self._call_openai_compatible(system_prompt)
            
            # Add response to history
            self.conversation_history.append({
                'role': 'assistant',
                'content': response
            })
            
            return response
            
        except Exception as e:
            error_msg = f"Error calling {self.PROVIDERS[self.provider]['name']}: {str(e)}"
            logger.error(error_msg)
            
            # Provide user-friendly error messages for common issues
            error_str = str(e).lower()
            
            # Get provider-specific dashboard link
            dashboard_links = {
                'xai': 'https://console.x.ai/',
                'openai': 'https://platform.openai.com/account/billing',
                'azure': 'https://portal.azure.com/',
                'gemini': 'https://makersuite.google.com/',
                'anthropic': 'https://console.anthropic.com/settings/billing',
                'ollama': 'http://localhost:11434'
            }
            dashboard_link = dashboard_links.get(self.provider, 'your provider dashboard')
            
            # Ollama-specific errors (connection refused = Ollama not running)
            if self.provider == 'ollama' and ('connection' in error_str or 'refused' in error_str or 'connect' in error_str):
                return (f"🔌 Ollama Not Running\n\n"
                       f"Could not connect to Ollama at {self.PROVIDERS['ollama']['base_url']}.\n\n"
                       f"To fix this:\n"
                       f"1. Make sure Ollama is installed (https://ollama.com)\n"
                       f"2. Start Ollama: run 'ollama serve' in a terminal\n"
                       f"3. Pull a model if you haven't: 'ollama pull {self.model}'\n\n"
                       f"If Ollama is on a different port, update the URL in Settings.")
            
            if 'deprecated' in error_str or ('404' in error_str and 'model' in error_str):
                # Check if it's a Gemini-specific model not found error
                if self.provider == 'gemini' and '404' in error_str and 'not found' in error_str:
                    return (f"🚫 Gemini API Issue\n\n"
                           f"The Gemini model '{self.model}' is not accessible with your API key.\n\n"
                           f"This usually means:\n"
                           f"1. 🔑 Your API key doesn't have Gemini API enabled\n"
                           f"2. 🌍 Gemini may not be available in your region\n"
                           f"3. 📋 You need to enable the Generative Language API\n\n"
                           f"Solutions:\n"
                           f"1. Enable Gemini API:\n"
                           f"   • Go to: https://console.cloud.google.com/\n"
                           f"   • Enable 'Generative Language API'\n"
                           f"   • Create new API key if needed\n\n"
                           f"2. Switch to a working provider (RECOMMENDED):\n"
                           f"   • Open Settings\n"
                           f"   • Choose: xAI, OpenAI, or Anthropic\n"
                           f"   • These providers work reliably!\n\n"
                           f"⚠️ NOTE: Gemini API setup is complex. For immediate use,\n"
                           f"we strongly recommend switching to OpenAI or Anthropic.\n\n"
                           f"Error details: {str(e)}")
                
                # Extract suggested model from error if available
                suggested_model = None
                if 'please use' in error_str:
                    try:
                        suggested_model = error_str.split('please use ')[1].split(' ')[0].strip('.')
                    except:
                        pass
                
                msg = (f"🔄 Model Deprecated\n\n"
                      f"The AI model '{self.model}' has been deprecated and is no longer available.\n\n")
                
                if suggested_model:
                    msg += f"Recommended: Use '{suggested_model}' instead.\n\n"
                
                msg += (f"Solutions:\n"
                       f"1. Open Settings in Garmin Chat\n"
                       f"2. Select {self.PROVIDERS[self.provider]['name']}\n"
                       f"3. Choose a different model from the dropdown\n"
                       f"4. Save and try again\n\n"
                       f"Available models:\n")
                
                for model in self.PROVIDERS[self.provider]['models']:
                    msg += f"  • {model}\n"
                
                msg += f"\nError details: {str(e)}"
                return msg
            
            elif '429' in error_str or 'quota' in error_str or 'rate limit' in error_str or 'resource_exhausted' in error_str:
                # Check if it's Gemini with specific rate limit info
                if self.provider == 'gemini':
                    # Extract retry delay if available
                    retry_seconds = None
                    if 'retry_delay' in error_str:
                        try:
                            import re
                            match = re.search(r'seconds:\s*(\d+)', error_str)
                            if match:
                                retry_seconds = int(match.group(1))
                        except:
                            pass
                    
                    msg = (f"⚠️ Gemini Rate Limit Reached\n\n"
                          f"You've hit Google Gemini's free tier rate limits.\n\n"
                          f"Free Tier Limits:\n"
                          f"• 15 requests per minute (RPM)\n"
                          f"• 1,500 requests per day (RPD)\n"
                          f"• 1 million tokens per minute (TPM)\n\n")
                    
                    if retry_seconds:
                        msg += f"⏱️ Retry in: {retry_seconds} seconds\n\n"
                    
                    msg += (f"Solutions:\n"
                           f"1. ⏰ WAIT ~60 seconds then try again (easiest)\n"
                           f"2. 💳 Upgrade to paid tier at: {dashboard_link}\n"
                           f"   - Paid tier: 2,000 RPM, much higher limits\n"
                           f"3. 🔄 Switch to a different AI provider in Settings\n"
                           f"   - Try xAI, OpenAI, or Anthropic (no free tier limits)\n\n"
                           f"💡 Tip: Gemini free tier is great but has strict rate limits.\n"
                           f"For heavy usage, consider:\n"
                           f"• Upgrading Gemini to paid ($$$)\n"
                           f"• Switching to OpenAI gpt-4o-mini ($ cheap!)\n"
                           f"• Switching to Anthropic claude-haiku ($ cheap!)\n\n"
                           f"Error details: {str(e)}")
                    return msg
                else:
                    # Generic rate limit error for other providers
                    return (f"⚠️ API Quota Exceeded\n\n"
                           f"Your {self.PROVIDERS[self.provider]['name']} account has exceeded its quota or rate limit.\n\n"
                           f"Solutions:\n"
                           f"1. Add credits or upgrade your plan at: {dashboard_link}\n"
                           f"2. Wait a few minutes if you hit a rate limit\n"
                           f"3. Switch to a different AI provider in Settings\n\n"
                           f"Common causes:\n"
                           f"• Unpaid bill or expired credit card\n"
                           f"• Free tier exhausted\n"
                           f"• Too many requests in a short time\n\n"
                           f"Error details: {str(e)}")
            
            elif '401' in error_str or 'unauthorized' in error_str or 'invalid' in error_str and 'key' in error_str:
                return (f"🔑 Invalid API Key\n\n"
                       f"Your {self.PROVIDERS[self.provider]['name']} API key appears to be invalid or expired.\n\n"
                       f"Solutions:\n"
                       f"• Check your API key in Settings\n"
                       f"• Generate a new API key from the provider's website\n"
                       f"• Make sure you copied the entire key with no extra spaces\n\n"
                       f"Error details: {str(e)}")
            
            elif '403' in error_str or 'forbidden' in error_str:
                return (f"🚫 Access Denied\n\n"
                       f"Your {self.PROVIDERS[self.provider]['name']} API key doesn't have permission to access this resource.\n\n"
                       f"Solutions:\n"
                       f"• Check that your API key has the correct permissions\n"
                       f"• Verify your account is in good standing\n"
                       f"• For Azure: verify your endpoint and deployment name\n\n"
                       f"Error details: {str(e)}")
            
            elif 'timeout' in error_str or 'timed out' in error_str:
                return (f"⏱️ Request Timeout\n\n"
                       f"The request to {self.PROVIDERS[self.provider]['name']} took too long.\n\n"
                       f"Solutions:\n"
                       f"• Check your internet connection\n"
                       f"• Try again in a moment\n"
                       f"• The AI service may be experiencing high load\n\n"
                       f"Error details: {str(e)}")
            
            elif 'connection' in error_str or 'network' in error_str:
                return (f"🌐 Connection Error\n\n"
                       f"Could not connect to {self.PROVIDERS[self.provider]['name']}.\n\n"
                       f"Solutions:\n"
                       f"• Check your internet connection\n"
                       f"• Verify the provider's service is online\n"
                       f"• Try again in a moment\n\n"
                       f"Error details: {str(e)}")
            
            else:
                return (f"❌ AI Service Error\n\n"
                       f"An error occurred while communicating with {self.PROVIDERS[self.provider]['name']}.\n\n"
                       f"Error details: {str(e)}\n\n"
                       f"You can try:\n"
                       f"• Switching to a different AI provider in Settings\n"
                       f"• Checking the provider's status page\n"
                       f"• Trying again in a moment")
    
    def _call_openai_compatible(self, system_prompt: str) -> str:
        """Call providers using OpenAI-compatible interface."""
        messages = [
            {'role': 'system', 'content': system_prompt}
        ] + self.conversation_history
        
        # For Azure, use deployment name instead of model
        model_param = self.azure_deployment if self.provider == 'azure' else self.model
        
        response = self.client.chat.completions.create(
            model=model_param,
            messages=messages,
            max_tokens=2000,
            temperature=0.7
        )
        
        return response.choices[0].message.content
    
    def _call_anthropic(self, system_prompt: str) -> str:
        """Call Anthropic using native SDK."""
        # Anthropic uses a different message format
        response = self.client.messages.create(
            model=self.model,
            max_tokens=2000,
            system=system_prompt,
            messages=self.conversation_history
        )
        
        return response.content[0].text
    
    def _call_gemini(self, system_prompt: str, user_message: str) -> str:
        """Call Gemini using new google-genai SDK."""
        try:
            from google.genai import types
            
            # Prepare the full prompt with system message
            # New API doesn't have separate system role, so combine them
            if len(self.conversation_history) == 1:  # First message
                full_prompt = f"{system_prompt}\n\nUser: {user_message}"
            else:
                # For continuing conversations, just send the user message
                # The history already has context
                full_prompt = user_message
            
            # The model name for the new API
            # Strip any existing prefix and use just the base name
            model_name = self.model.replace('models/', '').strip()
            
            logger.info(f"Calling Gemini with model: {model_name}")
            
            # The new google-genai API is simpler
            # Just pass the model name and content as strings
            response = self.client.models.generate_content(
                model=model_name,
                contents=full_prompt
            )
            
            logger.info(f"Gemini response type: {type(response)}")
            logger.info(f"Gemini response attributes: {dir(response)}")
            
            # Extract text from response - try multiple approaches
            # Approach 1: Direct text attribute
            if hasattr(response, 'text'):
                logger.info("Using response.text")
                return response.text
            
            # Approach 2: Candidates structure
            elif hasattr(response, 'candidates') and len(response.candidates) > 0:
                logger.info("Using response.candidates")
                candidate = response.candidates[0]
                if hasattr(candidate, 'content'):
                    content = candidate.content
                    if hasattr(content, 'parts') and len(content.parts) > 0:
                        return content.parts[0].text
                    elif hasattr(content, 'text'):
                        return content.text
            
            # Approach 3: Try to convert to string
            elif hasattr(response, '__str__'):
                logger.warning("Falling back to string conversion")
                return str(response)
            
            # If nothing works, log the full response structure
            logger.error(f"Could not extract text from response: {response}")
            logger.error(f"Response dir: {dir(response)}")
            raise ValueError(f"Unexpected response format from Gemini. Response type: {type(response)}")
            
        except Exception as e:
            # If native SDK fails, log detailed error and re-raise
            logger.error(f"Gemini native SDK error: {e}")
            logger.error(f"Error type: {type(e)}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            raise
    
    def reset_conversation(self):
        """Clear conversation history."""
        self.conversation_history = []
        logger.info("Conversation history cleared")
    
    @classmethod
    def get_available_providers(cls) -> Dict[str, Dict]:
        """Get list of available providers and their configurations."""
        return cls.PROVIDERS
    
    @classmethod
    def get_provider_models(cls, provider: str) -> List[str]:
        """Get available models for a specific provider."""
        if provider in cls.PROVIDERS:
            return cls.PROVIDERS[provider]['models']
        return []
