from __future__ import annotations
from typing import List, Dict

BAD_STATUSES = {"alarm", "error", "offline"}

def is_bad_wash(w: Dict) -> bool:
    if (w.get("status") or {}).get("type") in BAD_STATUSES:
        return True
    for m in w.get("modules", []):
        if m.get("status") in BAD_STATUSES:
            return True
    return False

def format_washes(washes: List[Dict], only_bad: bool) -> str:
    filtered = [w for w in washes if is_bad_wash(w)] if only_bad else washes
    if only_bad and not filtered:
        return "✅ Аварийных моек не обнаружено."
    lines = []
    lines.append("🧽 Сводка статусов (только аварийные):" if only_bad else "🧽 Сводка статусов:")
    for w in filtered:
        name = w.get("location_name") or f"ID {w.get('id')}"
        st = (w.get("status") or {}).get("type", "unknown")
        bad_mods = [m.get("name") for m in w.get("modules", []) if m.get("status") in BAD_STATUSES]
        lines.append(f"• {name}: {st}" + (f" (модули: {', '.join(bad_mods)})" if bad_mods else ""))
    text = "\n".join(lines)
    return text if len(text) <= 4000 else text[:3990] + "\n… (обрезано)"