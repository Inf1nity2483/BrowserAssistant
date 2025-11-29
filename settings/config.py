from betterconf import betterconf, DotenvProvider
from typing import Optional

@betterconf(provider=DotenvProvider(auto_load=True))
class Config:  
    open_ai_token: str
    model: str

config = Config()