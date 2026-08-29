"""
Reusable crowds.

The economics of a full run are brutal: building a world costs the bulk of the
money and forty minutes of waiting. Asking that world a question costs almost
nothing. So the expensive part should happen once, and the cheap part many
times.

A Crowd is a population captured from a finished run — the personas, not the
simulation engine. Polling one does not need OASIS running at all: a persona is
a block of text describing a person, and asking them something is a single LLM
call with that text as context. That turns a forty-minute, five-dollar pipeline
into a sub-minute, cents-level query, which is the only version of this product
a non-technical person will actually sit through.

Crowds are also the thing worth owning: expensive to build, cheap to serve, and
better the more they are used.
"""

import json
import os
import shutil
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from ..config import Config
from ..utils.logger import get_logger
from ..utils.safe_path import safe_join, validate_storage_id

logger = get_logger('spidernet.crowd')

# One poll fans out to this many personas at a time. Enough to be quick,
# not so many that a rate limit turns into a wall of failures.
MAX_POLL_CONCURRENCY = 8

# A poll larger than this is a research project, not a question.
MAX_SAMPLE_SIZE = 200


class CrowdVisibility(str, Enum):
    PRIVATE = "private"    # only the owner
    LIBRARY = "library"    # offered to every customer


@dataclass
class Crowd:
    """A population you can ask things, saved from a finished run."""
    crowd_id: str
    name: str
    description: str
    owner_key_id: Optional[str]
    size: int
    created_at: str
    source_simulation_id: Optional[str] = None
    graph_id: Optional[str] = None
    visibility: CrowdVisibility = CrowdVisibility.PRIVATE
    tags: List[str] = field(default_factory=list)
    poll_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["visibility"] = (
            self.visibility.value
            if isinstance(self.visibility, CrowdVisibility) else self.visibility
        )
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Crowd':
        return cls(
            crowd_id=data["crowd_id"],
            name=data.get("name", "Untitled crowd"),
            description=data.get("description", ""),
            owner_key_id=data.get("owner_key_id"),
            size=int(data.get("size", 0)),
            created_at=data.get("created_at", datetime.now().isoformat()),
            source_simulation_id=data.get("source_simulation_id"),
            graph_id=data.get("graph_id"),
            visibility=CrowdVisibility(data.get("visibility", "private")),
            tags=data.get("tags", []),
            poll_count=int(data.get("poll_count", 0)),
        )


class CrowdManager:
    """Stores crowds and polls them."""

    CROWDS_DIR = os.path.join(Config.UPLOAD_FOLDER, 'crowds')

    # ---- paths ---------------------------------------------------------

    @classmethod
    def _crowd_dir(cls, crowd_id: str, create: bool = False) -> str:
        validate_storage_id(crowd_id, "crowd_id")
        path = safe_join(cls.CROWDS_DIR, crowd_id)
        if create:
            os.makedirs(path, exist_ok=True)
        return path

    @classmethod
    def _meta_path(cls, crowd_id: str) -> str:
        return os.path.join(cls._crowd_dir(crowd_id), 'crowd.json')

    @classmethod
    def _people_path(cls, crowd_id: str) -> str:
        return os.path.join(cls._crowd_dir(crowd_id), 'people.json')

    # ---- lifecycle -----------------------------------------------------

    @classmethod
    def create(
        cls,
        name: str,
        people: List[Dict[str, Any]],
        owner_key_id: Optional[str] = None,
        description: str = "",
        source_simulation_id: Optional[str] = None,
        graph_id: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> Crowd:
        """Capture a population so it can be asked things later."""
        if not people:
            raise ValueError("A crowd needs at least one person.")

        crowd_id = f"crowd_{uuid.uuid4().hex[:12]}"
        crowd = Crowd(
            crowd_id=crowd_id,
            name=name,
            description=description,
            owner_key_id=owner_key_id,
            size=len(people),
            created_at=datetime.now().isoformat(),
            source_simulation_id=source_simulation_id,
            graph_id=graph_id,
            tags=tags or [],
        )

        cls._crowd_dir(crowd_id, create=True)
        with open(cls._people_path(crowd_id), 'w', encoding='utf-8') as f:
            json.dump(people, f, ensure_ascii=False)
        cls._save(crowd)

        logger.info(f"Captured crowd {crowd_id} ({len(people)} people) as {name!r}")
        return crowd

    @classmethod
    def _save(cls, crowd: Crowd) -> None:
        cls._crowd_dir(crowd.crowd_id, create=True)
        path = cls._meta_path(crowd.crowd_id)
        tmp = f"{path}.{uuid.uuid4().hex}.tmp"
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(crowd.to_dict(), f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)

    @classmethod
    def get(cls, crowd_id: str) -> Optional[Crowd]:
        try:
            path = cls._meta_path(crowd_id)
        except Exception:
            raise
        if not os.path.exists(path):
            return None
        with open(path, 'r', encoding='utf-8') as f:
            return Crowd.from_dict(json.load(f))

    @classmethod
    def get_people(cls, crowd_id: str) -> List[Dict[str, Any]]:
        path = cls._people_path(crowd_id)
        if not os.path.exists(path):
            return []
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)

    @classmethod
    def list_for(cls, owner_key_id: Optional[str]) -> List[Crowd]:
        """The caller's own crowds, plus everything in the shared library."""
        if not os.path.isdir(cls.CROWDS_DIR):
            return []

        out = []
        for entry in os.listdir(cls.CROWDS_DIR):
            try:
                crowd = cls.get(entry)
            except Exception:
                continue
            if crowd is None:
                continue
            is_library = crowd.visibility == CrowdVisibility.LIBRARY
            is_mine = crowd.owner_key_id is None or crowd.owner_key_id == owner_key_id
            if is_library or is_mine:
                out.append(crowd)

        return sorted(out, key=lambda c: c.created_at, reverse=True)

    @classmethod
    def delete(cls, crowd_id: str) -> bool:
        path = cls._crowd_dir(crowd_id)
        if not os.path.isdir(path):
            return False
        shutil.rmtree(path)
        return True

    # ---- polling -------------------------------------------------------

    @staticmethod
    def _describe(person: Dict[str, Any]) -> str:
        """Turn a stored persona into the context for one LLM call."""
        bits = []
        name = person.get("name") or person.get("user_name") or "Someone"
        bits.append(f"You are {name}.")
        for label, key in (
            ("You are", "age"), ("Gender", "gender"), ("You live in", "country"),
            ("Your job", "profession"), ("Personality type", "mbti"),
        ):
            value = person.get(key)
            if value:
                bits.append(f"{label}: {value}" if label != "You are" else f"You are {value} years old.")
        if person.get("bio"):
            bits.append(f"Your bio: {person['bio']}")
        if person.get("persona"):
            bits.append(f"About you:\n{person['persona']}")
        return "\n".join(bits)

    @classmethod
    def poll(
        cls,
        crowd_id: str,
        question: str,
        sample_size: int = 25,
        llm_client=None,
        max_tokens: int = 300,
    ) -> Dict[str, Any]:
        """
        Ask a question of a sample of the crowd.

        Each person answers independently, in character. Failures are reported
        rather than hidden, so a caller can tell "nobody answered" from
        "everyone agreed".

        Args:
            crowd_id: which crowd
            question: what to ask
            sample_size: how many people to ask
            llm_client: injected for testing; defaults to the configured client
            max_tokens: cap per answer

        Returns:
            {question, asked, answered, failed, responses: [...]}
        """
        if not question or not question.strip():
            raise ValueError("Ask an actual question.")
        if sample_size < 1:
            raise ValueError("sample_size must be at least 1")

        people = cls.get_people(crowd_id)
        if not people:
            raise ValueError(f"Crowd has nobody in it: {crowd_id}")

        sample_size = min(sample_size, MAX_SAMPLE_SIZE, len(people))
        # Deterministic sample: the same crowd polled twice asks the same
        # people, so two answers are comparable.
        sample = people[:sample_size]

        if llm_client is None:
            from ..utils.llm_client import LLMClient
            llm_client = LLMClient()

        def ask_one(person: Dict[str, Any]) -> Dict[str, Any]:
            messages = [
                {"role": "system", "content": (
                    f"{cls._describe(person)}\n\n"
                    "Answer as this person would, in their own voice. Be brief - "
                    "two or three sentences. Do not break character or mention "
                    "that you are an AI."
                )},
                {"role": "user", "content": question},
            ]
            answer = llm_client.chat(messages=messages, temperature=0.9,
                                     max_tokens=max_tokens)
            return {
                "name": person.get("name") or person.get("user_name"),
                "age": person.get("age"),
                "profession": person.get("profession"),
                "answer": answer,
            }

        responses: List[Dict[str, Any]] = []
        failures: List[Dict[str, Any]] = []

        with ThreadPoolExecutor(max_workers=MAX_POLL_CONCURRENCY) as pool:
            futures = {pool.submit(ask_one, p): p for p in sample}
            for future in as_completed(futures):
                person = futures[future]
                try:
                    responses.append(future.result())
                except Exception as e:
                    logger.warning(f"A person could not answer: {e}")
                    failures.append({
                        "name": person.get("name") or person.get("user_name"),
                        "error": str(e),
                    })

        crowd = cls.get(crowd_id)
        if crowd:
            crowd.poll_count += 1
            cls._save(crowd)

        return {
            "question": question,
            "asked": len(sample),
            "answered": len(responses),
            "failed": len(failures),
            "responses": responses,
            "failures": failures,
        }
