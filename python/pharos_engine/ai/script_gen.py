"""ScriptGenerator — wraps LLMClient to produce EntityScript classes."""
from __future__ import annotations

SYSTEM_PROMPT = """You are a Pharos Engine entity script generator.
Output ONLY valid Python code — no markdown, no explanation, no ``` fences.

Scripts define a class named EntityScript with any of these optional methods:

    def on_spawn(self, entity):
        \"\"\"Called once when the entity enters the scene.\"\"\"

    def on_tick(self, entity, dt: float):
        \"\"\"Called every frame. dt = seconds since last frame (~0.016).\"\"\"

    def on_despawn(self, entity):
        \"\"\"Called when entity is removed from scene.\"\"\"

    def on_collision(self, entity, other, overlap_vec):
        \"\"\"Called when entity collides with another (requires collision_shape set).\"\"\"

Available on `entity`:
  entity.position: list[float, float]   — world position [x, y]
  entity.rotation: float                — degrees clockwise
  entity.scale: float
  entity.velocity: list[float, float]   — if the entity has velocity
  entity.hp: float                      — if the entity has hp
  entity.energy: float                  — if the entity has energy (Bullet Strata)
  entity.strata_layer: int              — which strata layer (0/1/2)
  entity.scene                          — the Scene
  entity.scene._engine                  — the Engine
  entity.scene._engine.input            — InputManager
    .key_held("w"), .key_just_pressed("space"), .mouse_pos

Do not write any imports. Output only the EntityScript class definition.
"""


class ScriptGenerator:
    """Generate EntityScript Python classes from natural language prompts.

    Parameters
    ----------
    llm_client:
        An :class:`~Pharos Engine.ai.llm_client.LLMClient` instance.  If
        ``None`` a default instance is created on first use.
    """

    def __init__(self, llm_client=None):
        if llm_client is None:
            from pharos_engine.ai.llm_client import LLMClient
            llm_client = LLMClient()
        self._llm = llm_client

    def from_prompt(self, prompt: str) -> str:
        """Generate an EntityScript Python class from a natural language prompt.

        Parameters
        ----------
        prompt:
            Natural language description of the desired entity behaviour.

        Returns
        -------
        str
            Python source code for an ``EntityScript`` class.
        """
        response = self._llm.generate(prompt, system_prompt=SYSTEM_PROMPT, temperature=0.2)
        return self._clean(response)

    def _clean(self, code: str) -> str:
        """Strip markdown fences and leading/trailing whitespace."""
        code = code.strip()
        if code.startswith("```"):
            lines = code.splitlines()
            # Remove first fence line (e.g. "```python") and last fence line ("```")
            start = 1 if lines[0].startswith("```") else 0
            end = len(lines) - 1 if lines[-1].strip() == "```" else len(lines)
            code = "\n".join(lines[start:end]).strip()
        return code
