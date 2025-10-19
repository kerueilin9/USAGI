from typing import Optional, Mapping, Any
import os

from langchain_core.prompts import PromptTemplate
try:
    # chat model provided by the langchain-google-genai integration
    from langchain_google_genai import ChatGoogleGenerativeAI
except Exception as e:
    raise ImportError("langchain_google_genai (ChatGoogleGenerativeAI) is required by usagi.google_llm") from e


class GoogleGenerativeLLM:
    """Small adapter that exposes a callable interface compatible with prior code.

    Usage:
        llm = GoogleGenerativeLLM(model_name="gemini-2.0-flash")
        text = llm("Hello")
    """

    def __init__(self, model_name: str = "gemini-2.0-flash-exp", api_key: Optional[str] = None, temperature: float = 0.2):
        self.model_name = model_name
        self.api_key = api_key or os.getenv("GOOGLE_API_KEY")
        if not self.api_key:
            raise ValueError("GOOGLE_API_KEY not set; please set it in environment or pass api_key")

        self.temperature = float(temperature)

        # instantiate the LangChain model wrapper
        # Note: ChatGoogleGenerativeAI expects parameters such as `model` and `google_api_key`.
        self.llm = ChatGoogleGenerativeAI(
            model=self.model_name, 
            google_api_key=self.api_key, 
            temperature=self.temperature
        )

        # Create a simple prompt template for consistent interface
        self.prompt_template = PromptTemplate.from_template("{prompt}")

    def __call__(self, prompt: str) -> str:
        # Use the newer LangChain invoke pattern with prompt | llm
        try:
            chain = self.prompt_template | self.llm
            result = chain.invoke({"prompt": prompt})
            # result is an AIMessage object, extract content
            return result.content if hasattr(result, 'content') else str(result)
        except Exception as e:
            # surface a clearer error for the caller
            raise RuntimeError(f"Google LLM call failed: {e}") from e

    def _identifying_params(self) -> Mapping[str, Any]:
        return {"model_name": self.model_name, "temperature": self.temperature}
