"""
File: common.py
Description: Classes and variables used in multiple prompt template functions.
"""

import re
import os
from pydantic import BaseModel, field_validator
from utils import openai_config


def get_prompt_file_path(curr_file):
  return os.path.relpath(os.path.abspath(curr_file), os.path.pardir)


class ActionLoc(BaseModel):
  """
  Action Location class to be used for action sector and action arena
  Takes in "Answer: {name}" and reduces to just name.
  Also handles an input of {name}
  """

  area: str

  # Validator to clean up input and ensure only arena name is stored
  @field_validator("area")
  @classmethod
  def extract_name(cls, value):
    if value.startswith("Answer:"):
      # Remove "Answer:" prefix and strip surrounding spaces
      value = value[len("Answer:") :].strip()
    # Remove surrounding curly brackets if present
    value = re.sub(r"^\{|\}$", "", value).strip()
    return value.strip()  # Ensure no leading or trailing spaces


class FocalPoint(BaseModel):
  questions: list[str]


class ConvoTakeaways(BaseModel):
  takeaways: str


class StatementsSummary(BaseModel):
  statements_summary: str


class Poignancy(BaseModel):
  poignancy: int
