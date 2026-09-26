from pydantic import BaseModel, EmailStr, Field


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)


class Citation(BaseModel):
    title: str
    article_no: str
    chapter: str | None
    source_url: str
    distance: float

class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
