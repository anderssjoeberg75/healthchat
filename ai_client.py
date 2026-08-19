"""
Multi-provider AI client for HealthChat Desktop.
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
            'models': ['gemini-2.0-flash', 'gemini-2.0-flash-lite', 'gemini-2.0-pro-exp-02-05', 'gemini-1.5-flash', 'gemini-1.5-pro', 'gemini-1.5-flash-8b'],
            'default_model': 'gemini-2.0-flash',
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
    
    @classmethod
    def normalize_ollama_url(cls, raw_url: str) -> str:
        """
        Smart-format custom Ollama URLs/IPs into a full OpenAI-compatible endpoint.
        Examples:
            192.168.107.15               -> http://192.168.107.15:11434/v1
            http:/192.168.107.15:11434   -> http://192.168.107.15:11434/v1
            http://192.168.107.15        -> http://192.168.107.15:11434/v1
        """
        if not raw_url or not raw_url.strip():
            return 'http://localhost:11434/v1'
        
        import re
        from urllib.parse import urlparse

        url = raw_url.strip()
        url = re.sub(r'^(https?):/(?!/)', r'\1://', url)
        if not (url.startswith('http://') or url.startswith('https://')):
            url = 'http://' + url

        parsed = urlparse(url)
        host = parsed.hostname or 'localhost'
        port = parsed.port or 11434
        scheme = parsed.scheme or 'http'

        return f"{scheme}://{host}:{port}/v1"

    def _init_ollama(self, kwargs):
        """Initialize Ollama local/network client using OpenAI-compatible API."""
        raw_url = kwargs.get('ollama_base_url', self.PROVIDERS['ollama']['base_url'])
        base_url = self.normalize_ollama_url(raw_url)
        logger.info(f"Connecting to Ollama server at: {base_url}")
        return OpenAI(
            api_key='ollama',  # Ollama ignores the key but OpenAI client requires one
            base_url=base_url,
            timeout=300.0  # 5-minute timeout for local/network LLM generation
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
            system_prompt = """Du är en professionell personlig tränare och hälsocoach (COACH AI).
Du analyserar användarens hälso- och träningsdata (Garmin Connect & Withings: sömn, Body Battery, stress, vikt, fett%, muskelmassa, puls och träningspass) för att ge skräddarsydda och professionella tränings- och hälsoråd.

OBLIGATORISKA SPRÅK- OCH TERMINOLOGIREGLER:
1. Svara ALLTID på ren, grammatiskt felfri och naturlig svenska.
2. Förbjudna felöversättningar (använd ALDRIG dessa felaktiga ord):
   - Skriv "Analys & Bedömning" (ALDRIG "Sälsnämnd").
   - Skriv "Slutsats" (ALDRIG "Conclusio").
   - Skriv "Sömnpoäng" eller "Sömnbetyg" (ALDRIG "sömnskore").
   - Skriv "Andetag per minut" (ALDRIG "åtgärder per minut").
   - Skriv "Backar" eller "Stigning" (ALDRIG "häller").
   - Skriv "Dricka ordentligt" eller "Hålla vätskebalansen" (ALDRIG "hålla dig hyddrad").
   - För cykling: Använd HASTIGHET i km/h eller watt (skriv INTE cykeltempo som 8-9 min/km).
3. Håll en uppmuntrande, professionell och tydligt strukturerad ton.
4. OBLIGATORISK DATAKÄLLA: Du MÅSTE inkludera följande lista med exakta datum för din analys:
   📊 **Data & Datum som använts för denna analys:**
   - 🛌 **Sömn:** [Datum]
   - ⚡ **Body Battery & Stress:** [Datum]
   - ⚖️ **Vikt & Kroppssammansättning (Withings/Garmin):** [Datum och vikt om tillgängligt]
   - 🏃 **Träningspass:** [Datumintervall]

5. Strukturera ditt svar med tydliga rubriker:
   - **Analys & Bedömning**
   - **Rekommenderat träningspass**
   - **Vätska, Näring & Återhämtning**
   - **Slutsats & Mål**

6. Ge konkreta råd baserade på användarens mätvärden (sömn, Body Battery, vikt, kroppsfett, HRV och stress).
"""
        
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
                       f"1. Open Settings in HealthChat\n"
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
        
        timeout_val = 300.0 if self.provider == 'ollama' else 120.0
        response = self.client.chat.completions.create(
            model=model_param,
            messages=messages,
            max_tokens=2000,
            temperature=0.5 if self.provider == 'ollama' else 0.7,
            timeout=timeout_val
        )
        
        content = response.choices[0].message.content or ""
        # Clean CJK (Chinese/Japanese/Korean) tokens leaking from pre-training models like Qwen
        import re
        content = re.sub(r'[\u4e00-\u9fff]+', '', content)
        # Clean template dollar artifacts (e.g. ="$8.5")
        content = re.sub(r'=\s*\\?"\$[\d.]+\\?"', '', content)
        # Clean up any residual double spaces created by string replacements
        content = re.sub(r' +', ' ', content)
        return content.strip()
    
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

    @classmethod
    def fetch_models(cls, provider: str, api_key: str = "", base_url: str = "") -> List[str]:
        """
        Dynamically fetch available models directly from the provider's API.
        Falls back to default model list if API key is missing or request fails.
        """
        fallback = cls.get_provider_models(provider)
        
        if provider == 'gemini':
            if not api_key:
                return fallback
            try:
                import requests
                url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key.strip()}"
                resp = requests.get(url, timeout=6)
                if resp.status_code == 200:
                    data = resp.json()
                    models_list = []
                    for item in data.get('models', []):
                        name = item.get('name', '').replace('models/', '').strip()
                        methods = item.get('supportedGenerationMethods', [])
                        if 'generateContent' in methods and name and 'gemini' in name.lower():
                            models_list.append(name)
                    if models_list:
                        # Sort models: newest/highest versions first
                        models_list = sorted(list(set(models_list)), reverse=True)
                        logger.info(f"Dynamically fetched {len(models_list)} Gemini models from API")
                        return models_list
                else:
                    logger.warning(f"Gemini API returned status {resp.status_code} when fetching models: {resp.text}")
            except Exception as e:
                logger.warning(f"Could not dynamically fetch Gemini models: {e}")
                
        elif provider == 'openai':
            if not api_key:
                return fallback
            try:
                import requests
                headers = {"Authorization": f"Bearer {api_key.strip()}"}
                resp = requests.get("https://api.openai.com/v1/models", headers=headers, timeout=6)
                if resp.status_code == 200:
                    data = resp.json()
                    models_list = [m['id'] for m in data.get('data', []) if m['id'].startswith(('gpt-', 'o1-', 'o3-'))]
                    if models_list:
                        return sorted(list(set(models_list)), reverse=True)
            except Exception as e:
                logger.warning(f"Could not dynamically fetch OpenAI models: {e}")
                
        elif provider == 'ollama':
            url = base_url or 'http://localhost:11434/v1'
            base_host = url.rstrip('/').replace('/v1', '')
            hosts_to_try = [base_host]
            if 'localhost' in base_host:
                hosts_to_try.append(base_host.replace('localhost', '127.0.0.1'))
            elif '127.0.0.1' in base_host:
                hosts_to_try.append(base_host.replace('127.0.0.1', 'localhost'))

            import requests
            for h in hosts_to_try:
                # Try native /api/tags
                try:
                    resp = requests.get(f"{h}/api/tags", timeout=3)
                    if resp.status_code == 200:
                        models_list = [m['name'] for m in resp.json().get('models', [])]
                        if models_list:
                            logger.info(f"Dynamically fetched {len(models_list)} Ollama models from {h}/api/tags")
                            return sorted(models_list)
                except Exception as e:
                    logger.debug(f"Could not fetch Ollama models from {h}/api/tags: {e}")
                
                # Try OpenAI-compatible /v1/models
                try:
                    resp = requests.get(f"{h}/v1/models", timeout=3)
                    if resp.status_code == 200:
                        models_list = [m['id'] for m in resp.json().get('data', [])]
                        if models_list:
                            logger.info(f"Dynamically fetched {len(models_list)} Ollama models from {h}/v1/models")
                            return sorted(models_list)
                except Exception as e:
                    logger.debug(f"Could not fetch Ollama models from {h}/v1/models: {e}")
                
        return fallback
