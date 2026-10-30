"""What the agent can know about the warehouse, read from dbt's own artifacts.

dbt/target/manifest.json gives models, columns, descriptions, tests, contracts and lineage;
dbt/target/semantic_manifest.json gives the governed metrics. Nothing here touches the data.
"""
import json
import re
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

TARGET = Path(__file__).resolve().parent.parent / "dbt" / "target"


@dataclass
class Catalog:
    manifest: dict
    semantic: dict = field(default_factory=dict)

    @classmethod
    def load(cls, target: Path = TARGET) -> "Catalog":
        man = target / "manifest.json"
        if not man.exists():
            raise FileNotFoundError(f"{man} missing: run dbt parse (or scripts/run_all.py) first")
        sem = target / "semantic_manifest.json"
        return cls(json.loads(man.read_text(encoding="utf-8")),
                   json.loads(sem.read_text(encoding="utf-8")) if sem.exists() else {})

    # ---- nodes
    @cached_property
    def _nodes(self) -> dict[str, dict]:
        """Models, seeds, snapshots and sources by unique_id."""
        keep = ("model", "seed", "snapshot")
        out = {k: v for k, v in self.manifest.get("nodes", {}).items() if v.get("resource_type") in keep}
        out.update(self.manifest.get("sources", {}))
        return out

    @cached_property
    def _by_name(self) -> dict[str, str]:
        return {self._label(uid).lower(): uid for uid in self._nodes}

    @cached_property
    def _tests(self) -> dict[str, list[str]]:
        """Data and unit tests per node unique_id, as short readable labels."""
        out: dict[str, list[str]] = {}
        for t in self.manifest.get("nodes", {}).values():
            if t.get("resource_type") != "test":
                continue
            meta = t.get("test_metadata") or {}
            label = meta.get("name") or t["name"]
            col = t.get("column_name")
            label = f"{label}({col})" if col else label
            targets = [t["attached_node"]] if t.get("attached_node") else t.get("depends_on", {}).get("nodes", [])
            for uid in targets:
                out.setdefault(uid, []).append(label)
        for u in self.manifest.get("unit_tests", {}).values():
            for uid in u.get("depends_on", {}).get("nodes", [])[:1]:
                out.setdefault(uid, []).append(f"unit:{u['name']}")
        return out

    def resolve(self, name: str) -> str:
        key = (name or "").strip().lower()
        if key in self._by_name:
            return self._by_name[key]
        if key in self._nodes:
            return key
        close = [n for n in self._by_name if key and key in n][:5]
        hint = f"; did you mean {', '.join(close)}?" if close else ""
        raise KeyError(f"no model or source named {name!r}{hint}")

    def _label(self, uid: str) -> str:
        n = self._nodes.get(uid)
        if not n:
            return uid
        return f"{n['source_name']}.{n['name']}" if n.get("resource_type") == "source" else n["name"]

    def _layer(self, n: dict) -> str:
        if n.get("resource_type") != "model":
            return n.get("resource_type", "")
        path = "/" + n.get("original_file_path", "").replace("\\", "/")
        for layer in ("staging", "intermediate", "marts", "semantic"):
            if f"/{layer}/" in path:
                return layer
        return "model"

    # ---- public
    def search(self, query: str, limit: int = 8) -> list[dict]:
        """Models and metrics whose name, description or columns mention the query words."""
        words = [w for w in re.findall(r"[a-z0-9]+", (query or "").lower()) if len(w) > 2]
        if not words:
            return []
        hits = []
        for n in self._nodes.values():
            if n.get("resource_type") == "source":
                continue
            name = n["name"].lower()
            text = " ".join([n.get("description") or ""] +
                            [f"{c} {v.get('description') or ''}" for c, v in n.get("columns", {}).items()]).lower()
            score = sum(3 * (w in name) + text.count(w) for w in words)
            if score:
                score += 2 if self._layer(n) == "marts" else 0  # prefer the governed marts
                hits.append((score, {"kind": "model", "name": n["name"], "layer": self._layer(n),
                                     "description": _first_line(n.get("description"))}))
        for m in self.metrics():
            text = f"{m['name']} {m['label']} {m['description']}".lower()
            score = sum(3 * (w in m["name"]) + text.count(w) for w in words)
            if score:
                hits.append((score + 2, {"kind": "metric", "name": m["name"], "description": m["description"]}))
        hits.sort(key=lambda h: (-h[0], h[1]["name"]))
        return [h[1] for h in hits[:limit]]

    def describe(self, name: str) -> dict:
        uid = self.resolve(name)
        n = self._nodes[uid]
        cfg = n.get("config", {})
        return {
            "name": self._label(uid),
            "layer": self._layer(n),
            "relation": n.get("relation_name"),
            "description": (n.get("description") or "").strip(),
            "materialized": cfg.get("materialized"),
            "contract_enforced": bool((cfg.get("contract") or {}).get("enforced")),
            "columns": [{"name": c, "type": v.get("data_type"), "description": (v.get("description") or "").strip()}
                        for c, v in n.get("columns", {}).items()],
            "tests": sorted(self._tests.get(uid, [])),
            "upstream": [self._label(u) for u in self.manifest.get("parent_map", {}).get(uid, []) if u in self._nodes],
            "downstream": [self._label(u) for u in self.manifest.get("child_map", {}).get(uid, []) if u in self._nodes],
        }

    def lineage(self, name: str, direction: str = "upstream", depth: int = 10) -> list[dict]:
        """Breadth-first walk; each entry has the node, its layer and how many hops away it is."""
        if direction not in ("upstream", "downstream"):
            raise ValueError("direction must be upstream or downstream")
        edges = self.manifest.get("parent_map" if direction == "upstream" else "child_map", {})
        start = self.resolve(name)
        seen, frontier, out = {start}, [start], []
        for hop in range(1, depth + 1):
            nxt = []
            for uid in frontier:
                for v in edges.get(uid, []):
                    if v in self._nodes and v not in seen:
                        seen.add(v)
                        nxt.append(v)
                        out.append({"name": self._label(v), "layer": self._layer(self._nodes[v]), "hops": hop})
            frontier = nxt
            if not frontier:
                break
        return out

    def metrics(self) -> list[dict]:
        measures = {}
        for sm in self.semantic.get("semantic_models", []):
            model = (sm.get("node_relation") or {}).get("alias") or sm.get("name")
            for me in sm.get("measures", []):
                measures[me["name"]] = model
        out = []
        for m in self.semantic.get("metrics", []):
            tp = m.get("type_params") or {}
            used = [x["name"] for x in (tp.get("input_measures") or []) if x.get("name")]
            if (tp.get("measure") or {}).get("name"):
                used.append(tp["measure"]["name"])
            out.append({"name": m["name"], "label": m.get("label") or m["name"], "type": m.get("type"),
                        "description": (m.get("description") or "").strip(),
                        "built_on": sorted({measures[u] for u in used if u in measures})})
        return sorted(out, key=lambda x: x["name"])


def _first_line(text: str | None) -> str:
    return (text or "").strip().split("\n")[0][:200]
