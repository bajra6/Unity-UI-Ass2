"""Finite, explicitly labelled demo actions. This module does not inspect images."""
import re


def make_plan(command, completed_feedback=""):
    plan = []
    for match in re.finditer(r"\b(sit|stand|dance|roll|forward|backward|left|right|pick\s+up|drop)\b", command.lower()):
        word = match.group()
        action = {"forward": "move_forward", "backward": "move_backward",
                  "left": "turn_left", "right": "turn_right"}.get(word, re.sub(r"\s+", "_", word))
        if action in ("sit", "stand", "dance", "roll") and action + " completed" in completed_feedback.lower():
            continue
        plan.append((action, 30 if action.startswith("turn_") else .6 if action.startswith("move_") else 1))
    fetch_requested = bool(re.search(r"\b(fetch|bring|retrieve|find)\b", command.lower()))
    if fetch_requested:
        # Demonstrate the JSON movement pipeline; do not pretend to know where the ball is.
        plan = [(a, n) for a, n in plan if a not in ("pick_up", "drop")]
        plan.extend([("move_forward", .75), ("turn_left", 30), ("move_forward", .5)])
    if not plan:
        plan = [("stand", 1)]
    return plan[:8], fetch_requested


def next_action(state):
    index = state["cursor"]
    if index >= len(state["plan"]):
        action, amount = "finish", 1
        reason = "Placeholder demo finished. No vision model was used."
        if state["fetch"]:
            reason += " Fetch was not performed; use a working API for visual navigation."
    else:
        action, amount = state["plan"][index]
        reason = "Placeholder demo: scripted " + action.replace("_", " ") + "; no visual navigation."
        state["cursor"] += 1
    return {"action": action, "amount": amount, "reason": reason,
            "source": "placeholder", "fallback_error": state["error"]}
