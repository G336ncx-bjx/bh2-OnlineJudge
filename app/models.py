"""Pydantic 请求模型。"""
from typing import List, Optional

from pydantic import BaseModel, Field


class SampleCase(BaseModel):
    input: str
    output: str


class TestCase(BaseModel):
    input: str
    output: str


class ProblemCreate(BaseModel):
    id: str
    title: str
    description: str
    input_description: str
    output_description: str
    samples: List[SampleCase]
    constraints: str
    testcases: List[TestCase]
    hint: str = ""
    source: str = ""
    tags: List[str] = []
    time_limit: float = 3.0
    memory_limit: int = 128
    author: str = ""
    difficulty: str = ""


class LanguageCreate(BaseModel):
    name: str
    file_ext: str
    compile_cmd: Optional[str] = None
    run_cmd: str
    time_limit: Optional[float] = None
    memory_limit: Optional[int] = None


class SubmissionCreate(BaseModel):
    problem_id: str
    language: str
    code: str


class UserCreate(BaseModel):
    username: str
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


class RoleUpdate(BaseModel):
    role: str
